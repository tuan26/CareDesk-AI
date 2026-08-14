"""Locale resolution and safe translation fallback for public chat content."""
from typing import Any, Dict, Iterable, Optional

SUPPORTED_LOCALES = {"vi", "ja", "en"}
FALLBACK_LOCALE = {"vi": "en", "ja": "en", "en": "en"}


def say(locale: str, vi: str, en: str, ja: str) -> str:
    """Pick one of three hand-written strings. For short operational sentences
    that do not belong in the LANDING_TEXT/BOOKING_TEXT tables."""
    return {"vi": vi, "en": en, "ja": ja}.get(locale, en)


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
        "branch": "Cơ sở bạn muốn đến", "branch_any": "— Để phòng khám tư vấn giúp —",
        "branch_full": "chưa nhận đặt lịch online",
        "open_chat": "Trò chuyện với trợ lý ảo", "close_chat": "Đóng",
        "replying": "Đang trả lời…", "send": "Gửi",
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
        "branch": "Which location?", "branch_any": "— Let the clinic advise me —",
        "branch_full": "online booking unavailable",
        "open_chat": "Chat with the virtual assistant", "close_chat": "Close",
        "replying": "Replying…", "send": "Send",
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
        "branch": "ご希望の店舗", "branch_any": "— クリニックに相談する —",
        "branch_full": "オンライン予約不可",
        "open_chat": "バーチャルアシスタントと話す", "close_chat": "閉じる",
        "replying": "返信中…", "send": "送信",
    },
}


def ui_text(locale: str, key: str, **values: Any) -> str:
    """Localized widget copy with English as the safe final fallback."""
    text = UI_TEXT.get(normalize_locale(locale), UI_TEXT["en"]).get(key, UI_TEXT["en"].get(key, key))
    return text.format(**values)


# Server-rendered landing pages (/book/*). Kept apart from UI_TEXT because these
# strings are also what crawlers index, not just what a widget shows.
LANDING_TEXT = {
    "vi": {
        "book_cta": "Đặt lịch với trợ lý ảo", "call": "Gọi hotline",
        "locations": "Các cơ sở", "services": "Dịch vụ & bảng giá",
        "doctors": "Đội ngũ bác sĩ", "book_here": "Đặt lịch cơ sở này",
        "details": "Xem chi tiết", "book_title": "Đặt lịch khám",
        "book_body": "Trò chuyện với trợ lý ảo để được tư vấn dịch vụ và giữ chỗ khung giờ phù hợp.",
        "book_start": "Bắt đầu đặt lịch", "hours": "Giờ làm việc",
        "branch_info": "Thông tin cơ sở", "directions": "Chỉ đường",
        "book_at_branch": "Đặt lịch tại cơ sở này", "call_branch": "Gọi cơ sở",
        "other_branches": "Cơ sở khác", "back_to": "Về trang {name}",
        "minutes": "phút", "branch_count": "{n} cơ sở",
        "meta_desc": "{name}{where}. {branches} cơ sở, {services} dịch vụ. Đặt lịch khám trực tuyến với trợ lý ảo 24/7.",
        "meta_branch_desc": "{brand} — cơ sở {name}, {address}. {hours}Đặt lịch khám trực tuyến với trợ lý ảo 24/7.",
        "meta_hours": "Giờ làm việc {hours}. ", "title_suffix": "Đặt lịch khám",
        "powered": "Được vận hành bởi CareDesk AI", "not_found": "Không tìm thấy trang",
        # --- Form đặt lịch (không cần chat) ---
        "form_title": "Đặt lịch khám", "form_desc": "Đặt lịch khám tại {name} — chọn dịch vụ, ngày giờ phù hợp. Không cần tài khoản.",
        "form_cta": "Đặt lịch nhanh (không cần chat)", "or_chat": "hoặc trò chuyện với trợ lý ảo",
        "step_branch": "1. Chọn cơ sở", "step_service": "2. Chọn dịch vụ",
        "step_day": "3. Chọn ngày", "step_slot": "4. Chọn giờ",
        "step_contact": "5. Thông tin liên hệ",
        "any_doctor": "Bác sĩ bất kỳ", "pick_doctor": "Bác sĩ (không bắt buộc)",
        "no_slots": "Ngày này đã kín lịch hoặc phòng khám nghỉ. Bạn chọn ngày khác giúp em nhé.",
        "your_name": "Họ và tên", "your_phone": "Số điện thoại",
        "your_note": "Ghi chú (không bắt buộc)",
        "consent": "Tôi đồng ý để phòng khám liên hệ lại qua số điện thoại trên.",
        "submit": "Gửi yêu cầu đặt lịch",
        "not_confirmed": "Đây là yêu cầu đặt lịch. Lễ tân sẽ gọi xác nhận trong thời gian sớm nhất.",
        "done_title": "Đã nhận yêu cầu của bạn",
        "done_body": "Yêu cầu đặt lịch lúc {when} đã được gửi tới phòng khám. Lễ tân sẽ liên hệ để xác nhận.",
        "book_another": "Đặt thêm lịch khác", "change": "Đổi",
        "today": "Hôm nay", "tomorrow": "Ngày mai",
        # --- Chọn từng bước ---
        "pick": "Chọn", "picked": "Đã chọn", "step_of": "Bước {n}/{total}",
        "day_closed": "Nghỉ", "day_full": "Hết chỗ", "day_free": "{n} chỗ",
        "hint_branch": "Chọn cơ sở bạn muốn đến khám.",
        "hint_service": "Chọn dịch vụ bạn quan tâm. Có thể đổi lại sau khi lễ tân gọi.",
        "hint_day": "Ngày mờ là ngày phòng khám nghỉ hoặc đã kín lịch.",
        "hint_slot": "Chọn một khung giờ, rồi để lại số điện thoại.",
        "morning": "Buổi sáng", "afternoon": "Buổi chiều", "evening": "Buổi tối",
        "next_days": "14 ngày tới",
        "showcase_nav": "Kết quả", "reviews_title": "Khách hàng nói gì",
        "not_found_body": "Phòng khám hoặc cơ sở này không tồn tại, đã đổi liên kết hoặc đang tạm ngưng.",
    },
    "en": {
        "book_cta": "Book with the virtual assistant", "call": "Call hotline",
        "locations": "Locations", "services": "Services & pricing",
        "doctors": "Our doctors", "book_here": "Book at this location",
        "details": "View details", "book_title": "Book an appointment",
        "book_body": "Chat with our virtual assistant for advice and to hold a time slot.",
        "book_start": "Start booking", "hours": "Opening hours",
        "branch_info": "Location details", "directions": "Directions",
        "book_at_branch": "Book at this location", "call_branch": "Call this location",
        "other_branches": "Other locations", "back_to": "Back to {name}",
        "minutes": "min", "branch_count": "{n} locations",
        "meta_desc": "{name}{where}. {branches} locations, {services} services. Book online with our 24/7 virtual assistant.",
        "meta_branch_desc": "{brand} — {name}, {address}. {hours}Book online with our 24/7 virtual assistant.",
        "meta_hours": "Open {hours}. ", "title_suffix": "Book an appointment",
        "powered": "Powered by CareDesk AI", "not_found": "Page not found",
        "form_title": "Book an appointment", "form_desc": "Book at {name} — pick a service, a date and a time. No account needed.",
        "form_cta": "Quick booking (no chat)", "or_chat": "or talk to the virtual assistant",
        "step_branch": "1. Choose a location", "step_service": "2. Choose a service",
        "step_day": "3. Choose a date", "step_slot": "4. Choose a time",
        "step_contact": "5. Your details",
        "any_doctor": "Any doctor", "pick_doctor": "Doctor (optional)",
        "no_slots": "Fully booked or closed on this date. Please pick another day.",
        "your_name": "Full name", "your_phone": "Phone number",
        "your_note": "Note (optional)",
        "consent": "I agree to be contacted on the number above.",
        "submit": "Send booking request",
        "not_confirmed": "This is a request. Our reception will call to confirm shortly.",
        "done_title": "We have your request",
        "done_body": "Your request for {when} has been sent. Reception will contact you to confirm.",
        "book_another": "Book another", "change": "Change",
        "today": "Today", "tomorrow": "Tomorrow",
        "pick": "Select", "picked": "Selected", "step_of": "Step {n} of {total}",
        "day_closed": "Closed", "day_full": "Fully booked", "day_free": "{n} slots",
        "hint_branch": "Choose the location you would like to visit.",
        "hint_service": "Choose the treatment you are interested in. It can be changed when reception calls.",
        "hint_day": "Greyed days are closed or fully booked.",
        "hint_slot": "Pick a time, then leave your phone number.",
        "morning": "Morning", "afternoon": "Afternoon", "evening": "Evening",
        "next_days": "Next 14 days",
        "showcase_nav": "Results", "reviews_title": "What our clients say",
        "not_found_body": "This clinic or location does not exist, has moved, or is temporarily unavailable.",
    },
    "ja": {
        "book_cta": "バーチャルアシスタントで予約", "call": "ホットラインに電話",
        "locations": "店舗一覧", "services": "サービスと料金",
        "doctors": "医師紹介", "book_here": "この店舗を予約",
        "details": "詳細を見る", "book_title": "診察を予約する",
        "book_body": "バーチャルアシスタントに相談し、ご希望の時間を確保できます。",
        "book_start": "予約を開始", "hours": "営業時間",
        "branch_info": "店舗情報", "directions": "道順",
        "book_at_branch": "この店舗を予約", "call_branch": "この店舗に電話",
        "other_branches": "他の店舗", "back_to": "{name}に戻る",
        "minutes": "分", "branch_count": "{n}店舗",
        "meta_desc": "{name}{where}。{branches}店舗、{services}サービス。24時間対応のバーチャルアシスタントでオンライン予約。",
        "meta_branch_desc": "{brand} — {name}、{address}。{hours}24時間対応のバーチャルアシスタントでオンライン予約。",
        "meta_hours": "営業時間 {hours}。", "title_suffix": "診察予約",
        "powered": "CareDesk AI 提供", "not_found": "ページが見つかりません",
        "form_title": "診察予約", "form_desc": "{name}の予約 — 施術・日時をお選びください。アカウント登録は不要です。",
        "form_cta": "かんたん予約（チャット不要）", "or_chat": "またはAI受付と会話する",
        "step_branch": "1. 店舗を選ぶ", "step_service": "2. 施術を選ぶ",
        "step_day": "3. 日付を選ぶ", "step_slot": "4. 時間を選ぶ",
        "step_contact": "5. ご連絡先",
        "any_doctor": "指名なし", "pick_doctor": "医師（任意）",
        "no_slots": "この日は満席または休診です。別の日をお選びください。",
        "your_name": "お名前", "your_phone": "電話番号",
        "your_note": "備考（任意）",
        "consent": "上記の番号への連絡に同意します。",
        "submit": "予約リクエストを送信",
        "not_confirmed": "これは予約リクエストです。受付より確認のお電話をいたします。",
        "done_title": "リクエストを受け付けました",
        "done_body": "{when}のリクエストを送信しました。受付よりご連絡いたします。",
        "book_another": "別の予約をする", "change": "変更",
        "today": "本日", "tomorrow": "明日",
        "pick": "選択", "picked": "選択済み", "step_of": "ステップ {n}/{total}",
        "day_closed": "休診", "day_full": "満席", "day_free": "空き{n}枠",
        "hint_branch": "ご希望の店舗をお選びください。",
        "hint_service": "ご希望の施術をお選びください。受付からのお電話時に変更できます。",
        "hint_day": "薄い日付は休診または満席です。",
        "hint_slot": "時間をお選びのうえ、電話番号をご記入ください。",
        "morning": "午前", "afternoon": "午後", "evening": "夜間",
        "next_days": "今後14日間",
        "showcase_nav": "施術例", "reviews_title": "お客様の声",
        "not_found_body": "このクリニックまたは店舗は存在しないか、リンクが変更されたか、一時的に利用できません。",
    },
}


#: Column headings for the day picker, Monday first — the order date.weekday()
#: already uses, so the grid needs no arithmetic to place a date in a column.
#: A list, not a LANDING_TEXT entry, because landing_text formats strings.
WEEKDAY_NAMES = {
    "vi": ["T2", "T3", "T4", "T5", "T6", "T7", "CN"],
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    "ja": ["月", "火", "水", "木", "金", "土", "日"],
}


def weekday_names(locale: str) -> list:
    return WEEKDAY_NAMES.get(normalize_locale(locale), WEEKDAY_NAMES["en"])


def landing_text(locale: str, key: str, **values: Any) -> str:
    """Localized landing-page copy with English as the safe final fallback."""
    table = LANDING_TEXT.get(normalize_locale(locale), LANDING_TEXT["en"])
    text = table.get(key, LANDING_TEXT["en"].get(key, key))
    return text.format(**values) if values else text


def locale_for_conversation(conversation: Any, clinic: Optional[Any]) -> str:
    return normalize_locale(
        getattr(conversation, "locale", None), getattr(clinic, "default_locale", "vi") if clinic else "vi"
    )
