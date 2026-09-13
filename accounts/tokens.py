from django.contrib.auth.tokens import PasswordResetTokenGenerator


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    """
    Reuses Django's own secure, time-limited token machinery
    (itsdangerous-style signed token, expires per PASSWORD_RESET_
    TIMEOUT) instead of inventing a new token scheme. Including
    is_verified in the hash means a token is naturally invalidated
    the moment it's used once (is_verified flips True -> hash
    changes -> old token no longer validates), the same way Django's
    built-in password-reset tokens invalidate after the password
    changes.
    """

    def _make_hash_value(self, user, timestamp):
        return (
            str(user.pk) + str(timestamp) + str(user.is_verified)
        )


email_verification_token = EmailVerificationTokenGenerator()
