"""Locale resolution and safe translation fallback for public chat content."""
from typing import Any, Dict, Iterable, Optional

SUPPORTED_LOCALES = {"vi", "ja", "en"}
FALLBACK_LOCALE = {"vi": "en", "ja": "en", "en": "en"}


def normalize_locale(locale: Optional[str], default: str = "vi") -> str:
    value = (locale or default or "vi").lower().split("-", 1)[0]
    return value if value in SUPPORTED_LOCALES else (default if default in SUPPORTED_LOCALES else "vi")


def translation_for(
    localized_content: Optional[Dict[str, Dict[str, Any]]], locale: str
) -> Dict[str, Any]:
    """Return requested translation, then its explicit fallback, then an empty map."""
    content = localized_content or {}
    normalized = normalize_locale(locale)
    return content.get(normalized) or content.get(FALLBACK_LOCALE[normalized]) or {}


def missing_translation_locales(
    localized_content: Optional[Dict[str, Dict[str, Any]]], required: Iterable[str] = ("vi", "ja", "en")
) -> list[str]:
    content = localized_content or {}
    return [locale for locale in required if not content.get(locale)]


BOOKING_TEXT = {
    "vi": {
        "confirm": "Vui lòng xác nhận yêu cầu đặt lịch: trả lời 'đồng ý' để gửi yêu cầu, hoặc 'hủy' để chỉnh sửa.",
        "requested": "Yêu cầu đặt lịch của bạn đã được gửi. Đây chưa phải là lịch hẹn chính thức; lễ tân sẽ liên hệ xác nhận.",
    },
    "en": {
        "confirm": "Please confirm your booking request: reply 'yes' to submit it, or 'cancel' to make changes.",
        "requested": "Your booking request has been sent. This is not a confirmed appointment; our reception team will contact you.",
    },
    "ja": {
        "confirm": "予約リクエストを確認してください。送信するには「はい」、修正するには「キャンセル」と返信してください。",
        "requested": "予約リクエストを受け付けました。正式な予約ではありません。受付から確認のご連絡をします。",
    },
}


def booking_text(locale: str, key: str) -> str:
    resolved = normalize_locale(locale)
    return BOOKING_TEXT.get(resolved, BOOKING_TEXT["en"]).get(key, BOOKING_TEXT["en"][key])


def service_content(service: Any, locale: str) -> Dict[str, Any]:
    """Return a service's translated fields while safely retaining legacy values."""
    translated = translation_for(getattr(service, "localized_content", None), locale)
    return {
        "name": translated.get("name") or service.name,
        "description": translated.get("description") or service.description or "",
        "preparation_instructions": translated.get("preparation_instructions")
        or service.preparation_instructions
        or "",
        "faq": translated.get("faq") or service.faq_data or [],
    }


UI_TEXT = {
    "vi": {
        "title": "Lễ tân ảo CareDesk AI", "active": "Hoạt động 24/7",
        "consent_intro": "Vui lòng cung cấp thông tin để trợ lý ảo hỗ trợ bạn đặt lịch hẹn và tư vấn dịch vụ.",
        "name": "Họ và tên *", "phone": "Số điện thoại *", "email": "Email (Nhận nhắc lịch)",
        "referral": "Mã giới thiệu (nếu có)", "consent": "Tôi đồng ý cho phép CareDesk AI lưu trữ thông tin liên hệ để đặt lịch khám.",
        "start": "Bắt đầu trò chuyện", "connecting": "Đang kết nối...", "placeholder": "Nhập tin nhắn...",
        "welcome": "Chào bạn {name}, tôi là trợ lý ảo CareDesk AI. Tôi có thể giúp bạn giải đáp dịch vụ, bảng giá phòng khám hoặc hỗ trợ gửi yêu cầu đặt lịch. Bạn đang quan tâm dịch vụ nào ạ?",
        "connection_error": "Lỗi kết nối đến máy chủ. Vui lòng thử lại sau.", "send_error": "Rất tiếc, đã xảy ra lỗi kết nối. Vui lòng gửi lại.",
        "handoff": "Đang chuyển tiếp thông tin cho lễ tân hỗ trợ...", "agent_placeholder": "Lễ tân sẽ trả lời bạn ngay tại đây...",
    },
    "en": {
        "title": "CareDesk AI Virtual Receptionist", "active": "Available 24/7",
        "consent_intro": "Please provide your details so our virtual assistant can help with services and booking requests.",
        "name": "Full name *", "phone": "Phone number *", "email": "Email (for reminders)",
        "referral": "Referral code (optional)", "consent": "I consent to CareDesk AI storing my contact details for booking support.",
        "start": "Start chat", "connecting": "Connecting...", "placeholder": "Type a message...",
        "welcome": "Hello {name}, I am the CareDesk AI assistant. I can help with services, prices, clinic information, or a booking request. Which service are you interested in?",
        "connection_error": "Could not connect to the server. Please try again.", "send_error": "Sorry, a connection error occurred. Please send your message again.",
        "handoff": "Your information is being transferred to our reception team...", "agent_placeholder": "Our receptionist will reply here shortly...",
    },
    "ja": {
        "title": "CareDesk AI 受付アシスタント", "active": "24時間対応",
        "consent_intro": "サービスのご案内や予約リクエストのために、お客様情報をご入力ください。",
        "name": "お名前 *", "phone": "電話番号 *", "email": "メールアドレス（予約リマインダー用）",
        "referral": "紹介コード（任意）", "consent": "予約サポートのため、CareDesk AIが連絡先情報を保存することに同意します。",
        "start": "チャットを開始", "connecting": "接続中...", "placeholder": "メッセージを入力...",
        "welcome": "{name}様、こんにちは。CareDesk AIアシスタントです。サービス、料金、クリニック情報、予約リクエストをお手伝いします。ご希望のサービスはありますか？",
        "connection_error": "サーバーに接続できませんでした。もう一度お試しください。", "send_error": "接続エラーが発生しました。もう一度メッセージを送信してください。",
        "handoff": "受付スタッフへ情報を引き継いでいます...", "agent_placeholder": "受付スタッフがこちらで返信します...",
    },
}


def ui_text(locale: str, key: str, **values: Any) -> str:
    """Localized widget copy with English as the safe final fallback."""
    text = UI_TEXT.get(normalize_locale(locale), UI_TEXT["en"]).get(key, UI_TEXT["en"].get(key, key))
    return text.format(**values)


def locale_for_conversation(conversation: Any, clinic: Optional[Any]) -> str:
    return normalize_locale(
        getattr(conversation, "locale", None), getattr(clinic, "default_locale", "vi") if clinic else "vi"
    )
