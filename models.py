from google.appengine.ext import db

class Status(db.Model):
    status = db.StringProperty(required=True)
    json = db.TextProperty(required=True)
    user = db.StringProperty(required=True)
    tweet = db.StringProperty(required=True)
    generated = db.StringProperty(required=False)
    requester = db.StringProperty(required=False)

class OAuthToken(db.Model):
    token_key = db.StringProperty(required=True)
    token_secret = db.StringProperty(required=True)
    status = db.StringProperty(required=True)
