import bcrypt
from datetime import timedelta
import os
import re
import ujson
import uuid

import emails


class UserException(Exception):
    pass


class UserAlreadyExistsException(UserException):
    def __init__(self):
        super().__init__('User already exists')


class InvalidAuthLoginException(UserException):
    pass


class InvalidAuthTokenException(UserException):
    pass


class InvalidRegistrationToken(UserException):
    pass


class InvalidRegistrationUsername(UserException):
    def __init__(self):
        super().__init__('El username solo puede contener letras')


class InvalidRegistrationEmail(UserException):
    def __init__(self):
        super().__init__('El email no tiene formato correcto')


class UserManager(object):

    def __init__(self, redis_pool, app):
        super(UserManager, self).__init__()
        self.redis_pool = redis_pool
        self.app = app
        self.users = {}

    def _user_id(self, username):
        return 'user:{}'.format(username)

    def _registration_id(self, registration_token):
        return 'registration:{}'.format(registration_token)

    def _token_id(self, auth_token):
        return 'auth:{}'.format(auth_token)

    def _save_user(self, username, hash_password, email):
        self.app.logger.info('_save_user username: {}'.format(username))
        try:
            auth_token = str(uuid.uuid4())
            user = ujson.dumps({
                'username': username,
                'email': email,
                'password': hash_password,
                'auth_token': auth_token,
            })
            self.redis_pool.set(self._user_id(username), user)
            self.redis_pool.set(self._token_id(auth_token), username)
            emails.send_simple_message(
                email,
                'Your account in Megachess is confirmed!!!',
                (
                    '<p>This is your personal auth_token to play for username {}</p>'
                    '<p><strong>{}</strong></p>'
                ).format(username, auth_token)
            )
            return auth_token
        except Exception as e:
            self.app.logger.info('_save_user username: {} Exception'.format(username))
            raise e

    def _hash_password(self, password):
        return bcrypt.hashpw(
            password.encode('utf-8'), bcrypt.gensalt()
        )

    def _save_registration(self, username, hash_password, email):
        self.app.logger.info('_save_registration username: {}'.format(username))
        try:
            registration_token = str(uuid.uuid4())
            registration = ujson.dumps({
                'username': username,
                'email': email,
                'password': hash_password,
            })
            self.redis_pool.set(
                self._registration_id(registration_token),
                registration,
                ex=timedelta(days=1),
            )
            return registration_token
        except Exception as e:
            self.app.logger.info('_save_registration username: {} Exception'.format(username))
            raise e

    def _is_password_valid(self, password, user):
        return bcrypt.checkpw(
            password.encode('utf-8'),
            user['password'].encode('utf-8'),
        )

    def validate_registration(self, username, email):
        if not username.isalpha():
            raise InvalidRegistrationUsername()
        email_validator = '^[a-z]([w-]*[a-z]|[w-.]*[a-z]{2,}|[a-z])*@[a-z]([w-]*[a-z]|[w-.]*[a-z]{2,}|[a-z]){4,}?.[a-z]{2,}$'
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            raise InvalidRegistrationEmail()
        if self.redis_pool.get(self._user_id(username)):
            self.app.logger.info('register username: {} UserAlreadyExistsException'.format(username))
            raise UserAlreadyExistsException()

    def register(self, username, password, email, auto_hash=None):
        self.app.logger.info('register username: {}'.format(username))
        self.validate_registration(username, email)
        self.app.logger.info('register username: {} ok'.format(username))
        hash_password = self._hash_password(password)
        auto = auto_hash == os.getenv('AUTO_REGISTER_TOKEN') if auto_hash else False
        if auto:
            self._save_user(username, hash_password, email)
            return
        registration_token = self._save_registration(username, hash_password, email)
        domain_url = os.environ['DOMAIN_URL']
        emails.send_simple_message(
            email,
            'Welcome to Megachess!!',
            (
                '<p>Please confirm your email account</p>'
                '<a href="{}/confirm_registration?token={}">CONFIRM YOUR REGISTRATION</a>'
            ).format(domain_url, registration_token)
        )
        return True

    def confirm_registration(self, registration_token):
        registration_id = self._registration_id(registration_token)
        if not self.redis_pool.exists(registration_id):
            raise InvalidRegistrationToken()
        registration_string = self.redis_pool.get(registration_id)
        self.redis_pool.delete(registration_id)
        registration = ujson.loads(registration_string)
        self._save_user(
            registration['username'],
            registration['password'],
            registration['email'],
        )

    def get_auth_token(self, username, password):
        self.app.logger.info('get auth token username: {}'.format(username))
        user = self.get_user_by_username(username)
        if not self._is_password_valid(password, user):
            raise InvalidAuthLoginException()
        return user['auth_token']

    async def get_username_by_auth_token(self, auth_token):
        if not self.redis_pool.exists(self._token_id(auth_token)):
            raise InvalidAuthTokenException()
        return self.redis_pool.get(self._token_id(auth_token)).decode()

    def get_user_by_username(self, username):
        if not self.redis_pool.exists(self._user_id(username)):
            raise InvalidAuthLoginException()
        user_string = self.redis_pool.get(self._user_id(username))
        user = ujson.loads(user_string)
        if username not in user['username']:
            raise InvalidAuthLoginException()
        return user
