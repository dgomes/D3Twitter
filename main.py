#!/usr/bin/env python
#
# Copyright 2012 Diogo Gomes <diogogomes@gmail.com>.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import datetime
import os
import pickle
import webapp2
import tweepy
import sys
import logging
import json

from google.appengine.ext.webapp import template
from google.appengine.ext import db
from models import OAuthToken, Status

if os.environ.get('SERVER_SOFTWARE','').startswith('Devel'):
    CONSUMER_KEY="xxxxxxxxxxxxxxxx"
    CONSUMER_SECRET="yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy"
    CALLBACK = 'http://127.0.0.1:8080/'
else:
    CONSUMER_KEY="xxxxxxxxxxxxxxxx"
    CONSUMER_SECRET="yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy"
    CALLBACK = 'http://d3-twitter.appspot.com/'

class StatusPage(webapp2.RequestHandler):
    def nodeSize(self, followers):
        if followers > 400:
            return 10
        else:
            return followers/40

    def getAuth(self, status):
        # Build a new oauth handler and display authorization url to user.
        if status == "":
            self.response.out.write(template.render('error.html', {'message': "You need to supply a status id"}))
            return
        try:
            auth = tweepy.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET, CALLBACK+status)
            redirto = auth.get_authorization_url()
        except tweepy.TweepError, e:
            # Failed to get a request token
            self.response.out.write(template.render('error.html', {'message': e}))
            return
		# We must store the request token for later use in the callback page.
        request_token = OAuthToken(
                                   token_key = auth.request_token.key,
                                   token_secret = auth.request_token.secret,
                                   status = status
                                   )
        request_token.put()
        if status is not None:
            self.redirect(redirto)

    def get(self, unsafe_status):
        # Sanitize the status
        status = "".join([s for s in unsafe_status.split() if s.isdigit()])
        cacheStatus = Status.gql("WHERE status=:key", key=status).get()
        if cacheStatus is not None:
            self.response.out.write(template.render('d3.html', { "graph": cacheStatus.json, "screen_name": cacheStatus.user, "text": cacheStatus.tweet, "generated": cacheStatus.generated }))
            return

        oauth_token = self.request.get("oauth_token", None)
        oauth_verifier = self.request.get("oauth_verifier", None)
        if oauth_token is None:
            self.getAuth(status)
            return

        # Lookup the request token
        request_token = OAuthToken.gql("WHERE token_key=:key", key=oauth_token).get()
        if request_token is None:
            # We do not seem to have this request token, show an error.
            self.response.out.write(template.render('error.html', {'message': 'Invalid token!'}))
            return

        # Rebuild the auth handler
        auth = tweepy.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET)
        auth.set_request_token(request_token.token_key, request_token.token_secret)

        # Fetch the access token
        try:
            auth.get_access_token(oauth_verifier)
        except tweepy.TweepError, e:
            # Failed to get access token
            self.response.out.write(template.render('error.html', {'message': e}))
            return

        api = tweepy.API(auth)

        # We actually start HERE!!!
        # If the authentication was successful, we can start with our thing
        users_relationship = []
        users_retweet = []
        nodes = []

        logging.info('%s - %s API calls remaining until next hour', auth.get_username(), api.rate_limit_status()['remaining_hits'])


        try:
            status = request_token.status #retrieve the status id stored before doing auth
            logging.info('Getting status: %s', status)
            tweet = api.get_status(id=status)

            retweets = api.retweets(id=status)
            retweets_by = tweepy.Cursor(api.retweeted_by,id=status, count=100)
        except tweepy.TweepError, e:
            logging.error("error retrieving status %s - %s", status, e)
            self.response.out.write(template.render('error.html', {'message': e}))
            return

        if(len(retweets) == 0 or retweets[0].retweet_count == 0):
            logging.error("error no retweets for status %s", status)
            self.response.out.write(template.render('error.html', {'message': 'I\'m sorry but no one has retweeted this status (yet)!'}))
            return

        #store the user who started everything
        nodes.append(tweet.user.id)
        users_retweet.append({"id": nodes.index(tweet.user.id), "name": tweet.user.screen_name, "url": "http://twitter.com/"+tweet.user.screen_name, "nodeSize": self.nodeSize(tweet.user.followers_count), "layer": 1});

        #store all the users who retweeted
        for u in retweets_by.items():
            nodes.append(u.id)
            users_retweet.append({"id": nodes.index(u.id), "name": u.screen_name, "url": "http://twitter.com/"+u.screen_name, "nodeSize": self.nodeSize(u.followers_count), "layer": 0});
        logging.debug('%d retweets were made, showing %d', retweets[0].retweet_count, len(users_retweet)) #not everytime do these value match!

        #figure out how everyone is related
        for u in users_retweet:
            followers = []
            try:
                followers = tweepy.Cursor(api.followers_ids, screen_name=u['name']).items()
            except tweepy.TweepError, e:
                logging.error("error retrieving info for %s - %s", u['name'], e)
            try:
                for f in followers:
                    if f in nodes:
                        users_relationship.append({"source": nodes.index(f), "target": u['id']})
            except tweepy.TweepError, e:
                logging.error("error retrieving info for %s - %s", u['name'], e)
                self.response.out.write(template.render('error.html', {'message': 'I\'m sorry but you have reached twitters rate limits :( Please try later using a status with fewer retweets.'}))
                return

        logging.debug('you now have %s API calls remaining until next hour', api.rate_limit_status()['remaining_hits'])

        #store everything in the datastore
        status_obj = Status(
                            key_name = status,
                            status = status,
                            json = json.dumps({"links": users_relationship, "nodes":users_retweet}, indent=4),
                            tweet = tweet.text,
                            user = tweet.user.screen_name,
                            generated = str(datetime.datetime.now()),
                            requester = auth.get_username()
                            )
        status_obj.put()

        #redirect to the same page without tokens for final rendering
        self.redirect(self.request.path_url)


app = webapp2.WSGIApplication([
                               # OAuth example
                               ('/(.*)', StatusPage)
                               ],
                              debug=True)
