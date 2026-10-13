from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.api import APIError

from .models import AccessToken, User

# ================ Main Services : Registration and Login =================
def register_account(data):
    username = username_from(data.get("username"))
    name = data.get("name")
    password = data.get("password")
    gender = data.get("gender", User.Gender.UNKNOWN)
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 40:
        raise APIError("이름을 다시 확인해 주세요.")
    if gender not in User.Gender.values:
        raise APIError("관계 표시를 다시 선택해 주세요.")
    if not isinstance(password, str) or len(password) > 128:
        raise APIError("비밀번호를 다시 확인해 주세요.")
    if User.objects.filter(username__iexact=username).exists():
        raise APIError("이미 사용 중인 아이디예요.", 409)

    user = User(username=username, display_name=name.strip(), gender=gender)
    try:
        validate_password(password, user)
    except ValidationError as error:
        raise APIError("비밀번호는 10자 이상으로, 이름과 비슷하거나 흔한 문자열·숫자만 사용할 수 없어요.") from error
    user.set_password(password)
    try:
        user.full_clean()
    except ValidationError as error:
        if "username" in error.error_dict and User.objects.filter(username__iexact=username).exists():
            raise APIError("이미 사용 중인 아이디예요.", 409) from error
        raise APIError("계정 정보를 다시 확인해 주세요.") from error
    try:
        with transaction.atomic():
            user.save()
            return session_data(user)
    except IntegrityError as error:
        raise APIError("이미 사용 중인 아이디예요.", 409) from error


def login_account(request, data):
    username = username_from(data.get("username"))
    password = data.get("password")
    if not isinstance(password, str):
        raise APIError("아이디 또는 비밀번호가 맞지 않아요.", 401)
    user = authenticate(request, username=username, password=password)
    if user is None:
        raise APIError("아이디 또는 비밀번호가 맞지 않아요.", 401)
    return session_data(user)

# ================= Helper Services : Data Formatting =================
def username_from(raw):
    if not isinstance(raw, str):
        raise APIError("아이디를 다시 확인해 주세요.")
    username = User.normalize_username(raw.strip()).casefold()
    if not username or len(username) > 150:
        raise APIError("아이디를 다시 확인해 주세요.")
    try:
        UnicodeUsernameValidator()(username)
    except ValidationError as error:
        raise APIError("아이디에 사용할 수 없는 문자가 있어요.") from error
    return username


def account_data(user):
    return {
        "user_id": user.pk,
        "username": user.username,
        "name": user.display_name,
        "gender": user.gender,
    }


def session_data(user):
    return {"token": AccessToken.issue(user), **account_data(user)}


