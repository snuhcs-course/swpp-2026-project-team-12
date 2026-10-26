from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.api import APIError
from integrations.speech import voices

from .models import AccessToken, User

# ================ Main Services : Registration and Login =================
def register_account(data):
    username = username_from(data.get("username"))
    name = data.get("name")
    password = data.get("password")
    gender = data.get("gender")
    tts_voice = data.get("tts_voice", "")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 40:
        raise APIError("이름을 다시 확인해 주세요.")
    if gender not in (User.Gender.MALE, User.Gender.FEMALE):
        raise APIError("성별을 선택해 주세요.")
    if tts_voice != "" and not voices.is_known(tts_voice):
        raise APIError("목소리를 다시 선택해 주세요.")
    if not isinstance(password, str) or len(password) > 128:
        raise APIError("비밀번호를 다시 확인해 주세요.")
    if User.objects.filter(username__iexact=username).exists():
        raise APIError("이미 사용 중인 아이디예요.", 409)

    user = User(username=username, display_name=name.strip(), gender=gender, tts_voice=tts_voice)
    try:
        validate_password(password, user)
    except ValidationError as error:
        raise APIError("비밀번호는 10자 이상이며 숫자를 포함해야 해요. 아이디·이름과 비슷한 값, 흔한 비밀번호, 숫자만으로는 만들 수 없어요.") from error
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
        "tts_voice": voices.effective(user.tts_voice),
    }


def session_data(user):
    return {"token": AccessToken.issue(user), **account_data(user)}


@transaction.atomic
def update_account(user, data):
    allowed = {"name", "tts_voice", "current_password", "new_password"}
    if not data or set(data) - allowed:
        raise APIError("수정할 계정 정보를 다시 확인해 주세요.")
    if ("current_password" in data) != ("new_password" in data):
        raise APIError("비밀번호를 바꾸려면 현재 비밀번호와 새 비밀번호를 함께 입력해 주세요.")
    # Work from a fresh locked row so parallel profile edits do not overwrite a password.
    user = User.objects.select_for_update().get(pk=user.pk)
    old_name = user.display_name
    if "name" in data:
        name = data["name"]
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 40:
            raise APIError("이름은 1~40자로 입력해 주세요.")
        user.display_name = name.strip()
    if "tts_voice" in data:
        if not voices.is_known(data["tts_voice"]):
            raise APIError("목소리를 다시 선택해 주세요.")
        user.tts_voice = data["tts_voice"]
    changing_password = "new_password" in data
    if changing_password:
        current, replacement = data["current_password"], data["new_password"]
        if not isinstance(current, str) or not user.check_password(current):
            raise APIError("현재 비밀번호가 맞지 않아요.")
        if not isinstance(replacement, str) or not 10 <= len(replacement) <= 128:
            raise APIError("새 비밀번호는 10~128자로 입력해 주세요.")
        try:
            validate_password(replacement, user)
        except ValidationError as error:
            raise APIError("새 비밀번호는 10자 이상이며 숫자를 포함해야 해요. 아이디·이름과 비슷한 값, 흔한 비밀번호, 숫자만으로는 만들 수 없어요.") from error
        user.set_password(replacement)
    user.save(update_fields=["display_name", "tts_voice", "password"])
    if old_name != user.display_name:
        # Cached generated wording can contain the previous display name.
        from apps.posts.models import AdaptedMessage
        from apps.digests.models import Digest
        from apps.families.models import FamilyRoom, Membership
        from django.db.models import F
        from django.utils import timezone
        rooms = Membership.objects.filter(user=user).values("room_id")
        FamilyRoom.objects.filter(pk__in=rooms).update(tree_version=F("tree_version") + 1)
        AdaptedMessage.objects.filter(post__room_id__in=rooms).update(
            status="pending", text="", updated_at=timezone.now()
        )
        Digest.objects.filter(room_id__in=rooms).update(
            status="pending", text="", updated_at=timezone.now()
        )
    result = account_data(user)
    if changing_password:
        AccessToken.objects.filter(user=user).delete()
        result["token"] = AccessToken.issue(user)
    return result
