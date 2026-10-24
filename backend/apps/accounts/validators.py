from django.core.exceptions import ValidationError


class NumberRequiredValidator:
    """Apply the same number requirement to registration and password changes."""

    def validate(self, password, user=None):
        if not any("0" <= character <= "9" for character in password):
            raise ValidationError("비밀번호에 숫자를 한 개 이상 포함해 주세요.", code="password_no_number")

    def get_help_text(self):
        return "비밀번호에 숫자(0~9)를 한 개 이상 포함해야 해요."
