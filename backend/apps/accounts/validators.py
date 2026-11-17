from django.core.exceptions import ValidationError


class NumberRequiredValidator:
    """Apply the same number requirement to registration and password changes."""

    def validate(self, password, user=None):
        if not any("0" <= character <= "9" for character in password):
            raise ValidationError("비밀번호에 숫자를 한 개 이상 포함해 주세요.", code="password_no_number")

    def get_help_text(self):
        return "비밀번호에 숫자(0~9)를 한 개 이상 포함해야 해요."


def password_error_message(error):
    """Explain only the rules rejected by the configured Django validators."""
    messages = []
    for item in error.error_list:
        reasons = {
            "password_too_short": f"비밀번호는 {item.params.get('min_length', 10) if item.params else 10}자 이상으로 입력해 주세요.",
            "password_too_common": "너무 흔한 비밀번호예요. 다른 비밀번호를 만들어 주세요.",
            "password_entirely_numeric": "숫자만으로는 만들 수 없어요. 문자도 함께 넣어 주세요.",
            "password_too_similar": "계정 정보와 너무 비슷해요. 아이디·이름과 다른 비밀번호를 만들어 주세요.",
            "password_no_number": "비밀번호에 숫자를 한 개 이상 포함해 주세요.",
        }
        message = reasons.get(item.code, " ".join(item.messages))
        if message not in messages:
            messages.append(message)
    return "\n".join(messages)
