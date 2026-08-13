"""Which advert paid for this patient, and what that channel earned.

The report this feeds decides where a clinic spends next month's budget, so the
counting rules matter more than the plumbing:

  * first touch wins, always — otherwise the retargeting ad that catches someone
    on the way back steals credit from the campaign that found them
  * a patient is counted once — otherwise a channel bringing a few loyal
    patients outscores one bringing many new ones, purely by double counting
"""
import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models.models import (
    Appointment, BookingRequest, Branch, Clinic, Doctor, PatientLead,
    RevenueRecord, Service,
)
from backend.app.services import attribution, funnel

engine = create_engine("sqlite:///:memory:")
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class FakeRequest:
    """Just enough of a request for the capture helpers."""
    def __init__(self, path="/book/caredesk", params=None, referer=None, cookies=None):
        self.query_params = params or {}
        self.headers = {"referer": referer} if referer else {}
        self.cookies = cookies or {}
        self.url = type("U", (), {"path": path})


class FakeResponse:
    def __init__(self):
        self.cookies = {}

    def set_cookie(self, name, value, **kw):
        self.cookies[name] = value


@pytest.fixture(scope="function")
def db():
    Base.metadata.create_all(bind=engine)
    s = TestingSessionLocal()
    yield s
    s.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def clinic(db):
    c = Clinic(name="CareDesk", is_active=True)
    db.add(c)
    db.flush()
    branch = Branch(clinic_id=c.id, name="CS1", address="1 A", is_active=True)
    service = Service(clinic_id=c.id, name="Pico", price=2500000, duration_minutes=60)
    doctor = Doctor(clinic_id=c.id, name="BS A", is_active=True)
    db.add_all([branch, service, doctor])
    db.commit()
    return {"clinic": c, "branch": branch, "service": service, "doctor": doctor}


def _lead(db, clinic, name, days_ago=5, **attrs):
    p = PatientLead(clinic_id=clinic["clinic"].id, full_name=name, phone="0900000001",
                    consent_given=True,
                    first_seen_at=datetime.datetime.now() - datetime.timedelta(days=days_ago),
                    **attrs)
    db.add(p)
    db.commit()
    return p


def _visit(db, clinic, patient, status="completed", revenue=None, days_ago=2):
    start = datetime.datetime.now() - datetime.timedelta(days=days_ago)
    a = Appointment(clinic_id=clinic["clinic"].id, branch_id=clinic["branch"].id,
                    service_id=clinic["service"].id, doctor_id=clinic["doctor"].id,
                    patient_id=patient.id, status=status,
                    start_time=start, end_time=start + datetime.timedelta(minutes=60))
    db.add(a)
    db.flush()
    if revenue:
        db.add(RevenueRecord(clinic_id=clinic["clinic"].id, patient_id=patient.id,
                             appointment_id=a.id, amount=revenue, source="ai_chat"))
    db.commit()
    return a


# --- capturing the first touch ------------------------------------------------

def test_utm_parameters_are_captured(db):
    req = FakeRequest(params={"utm_source": "facebook", "utm_medium": "cpc",
                              "utm_campaign": "pico-thang-8", "utm_content": "video-a"})
    data = attribution.from_request(req)

    assert data["utm_source"] == "facebook"
    assert data["utm_campaign"] == "pico-thang-8"
    assert data["landing_path"] == "/book/caredesk"


def test_a_click_id_alone_still_identifies_the_platform(db):
    """Ad platforms frequently send fbclid/gclid and no utm_source at all."""
    assert attribution.from_request(FakeRequest(params={"fbclid": "abc"}))["utm_source"] == "facebook"
    assert attribution.from_request(FakeRequest(params={"gclid": "abc"}))["utm_source"] == "google"
    assert attribution.from_request(FakeRequest(params={"ttclid": "abc"}))["utm_source"] == "tiktok"


def test_an_untagged_referral_is_read_from_the_referrer(db):
    data = attribution.from_request(FakeRequest(referer="https://www.google.com/search?q=tri+nam"))
    assert data["utm_source"] == "google"
    assert data["utm_medium"] == "referral"


def test_first_touch_is_never_overwritten(db):
    """The whole point. A retargeting click must not steal the credit."""
    first = FakeResponse()
    attribution.remember(FakeRequest(params={"utm_source": "facebook",
                                             "utm_campaign": "pico-thang-8"}), first)
    stored = first.cookies[attribution.COOKIE_NAME]

    second = FakeResponse()
    kept = attribution.remember(
        FakeRequest(params={"utm_source": "google", "utm_campaign": "retarget"},
                    cookies={attribution.COOKIE_NAME: stored}),
        second)

    assert kept["first"]["utm_source"] == "facebook"
    assert kept["first"]["utm_campaign"] == "pico-thang-8"
    # The later click is not discarded — it becomes latest touch, which answers
    # a different question and must never feed acquisition credit.
    assert kept["latest"]["utm_source"] == "google"
    assert kept["touches"] == 2


def test_a_direct_visit_does_not_burn_the_cookie(db):
    """If a plain visit claimed the slot, the advert clicked an hour later would
    find it already taken and lose its credit."""
    response = FakeResponse()
    data = attribution.remember(FakeRequest(), response)

    assert data == {}
    assert attribution.COOKIE_NAME not in response.cookies


def test_a_corrupt_cookie_does_not_break_the_page(db):
    assert attribution.read_cookie(
        FakeRequest(cookies={attribution.COOKIE_NAME: "{khong-phai-json"})) == {}


def test_attribution_only_fills_blanks_on_a_returning_patient(db, clinic):
    """The campaign that earned the relationship keeps it."""
    patient = _lead(db, clinic, "Khach cu", utm_source="facebook", utm_campaign="thang-7")
    attribution.apply_to_lead(patient, {"utm_source": "tiktok", "utm_campaign": "thang-8"})

    assert patient.utm_source == "facebook"
    assert patient.utm_campaign == "thang-7"


# --- naming the channel --------------------------------------------------------

def test_channel_prefers_the_tagged_source(db, clinic):
    assert attribution.channel_of(_lead(db, clinic, "A", utm_source="TikTok")) == "tiktok"


def test_an_untagged_walk_in_is_direct_not_unknown(db, clinic):
    """"Unknown" reads as missing data. A QR code on the door genuinely is
    direct, and the distinction changes what the clinic does next."""
    assert attribution.channel_of(_lead(db, clinic, "B", source="web")) == "direct"


def test_a_widget_conversation_keeps_its_channel(db, clinic):
    assert attribution.channel_of(_lead(db, clinic, "C", source="zalo")) == "zalo"


# --- the funnel ---------------------------------------------------------------

def test_the_funnel_counts_each_stage(db, clinic):
    booked = _lead(db, clinic, "Da dat", utm_source="facebook")
    _visit(db, clinic, booked, status="confirmed")

    came = _lead(db, clinic, "Da den", utm_source="facebook")
    _visit(db, clinic, came, status="completed", revenue=2500000)

    _lead(db, clinic, "Chi hoi", utm_source="facebook")

    f = funnel.build(db, clinic["clinic"].id)
    row = next(r for r in f.channels if r.channel == "facebook")
    assert (row.leads, row.bookings, row.visits, row.revenue) == (3, 2, 1, 2500000)
    assert row.booking_rate == 66.7
    assert row.show_rate == 50.0


def test_channels_are_reported_separately(db, clinic):
    fb = _lead(db, clinic, "FB", utm_source="facebook")
    _visit(db, clinic, fb, revenue=3000000)
    tt = _lead(db, clinic, "TT", utm_source="tiktok")
    _visit(db, clinic, tt, revenue=1000000)

    f = funnel.build(db, clinic["clinic"].id)
    by_channel = {r.channel: r.revenue for r in f.channels}
    assert by_channel == {"facebook": 3000000, "tiktok": 1000000}
    assert f.channels[0].channel == "facebook", "sắp xếp theo doanh thu"


def test_a_patient_is_counted_once_however_often_they_come(db, clinic):
    """Otherwise a channel bringing a few regulars beats one bringing many new
    patients, purely by counting the same person repeatedly."""
    patient = _lead(db, clinic, "Khach quen", utm_source="google")
    for _ in range(3):
        _visit(db, clinic, patient, revenue=1000000)

    row = funnel.build(db, clinic["clinic"].id).channels[0]
    assert row.leads == 1
    assert row.visits == 1
    assert row.revenue == 3000000, "doanh thu cộng dồn, còn người thì đếm một lần"


def test_a_booking_request_counts_as_booked(db, clinic):
    """Requiring a confirmed appointment would blame the channel for the
    clinic's own callback backlog."""
    patient = _lead(db, clinic, "Cho goi lai", utm_source="facebook")
    db.add(BookingRequest(clinic_id=clinic["clinic"].id, patient_id=patient.id,
                          service_or_need="Pico", full_name="Cho goi lai",
                          contact_method="phone", contact_value="0900000001"))
    db.commit()

    row = funnel.build(db, clinic["clinic"].id).channels[0]
    assert row.bookings == 1 and row.visits == 0


def test_patients_outside_the_window_are_excluded(db, clinic):
    _lead(db, clinic, "Cu", days_ago=200, utm_source="facebook")
    _lead(db, clinic, "Moi", days_ago=3, utm_source="facebook")

    f = funnel.build(db, clinic["clinic"].id,
                     start_date=datetime.date.today() - datetime.timedelta(days=30))
    assert f.leads == 1


def test_revenue_follows_first_touch_not_the_month_it_arrived(db, clinic):
    """A patient found in August and treated in September belongs to August's
    campaign — that is the campaign the clinic paid for."""
    patient = _lead(db, clinic, "Nghi lau", days_ago=25, utm_source="facebook",
                    utm_campaign="thang-8")
    _visit(db, clinic, patient, revenue=5000000, days_ago=1)

    f = funnel.build(db, clinic["clinic"].id, by_campaign=True)
    row = f.channels[0]
    assert row.campaign == "thang-8"
    assert row.revenue == 5000000


def test_campaign_breakdown_splits_one_channel(db, clinic):
    a = _lead(db, clinic, "A", utm_source="facebook", utm_campaign="pico")
    _visit(db, clinic, a, revenue=2000000)
    b = _lead(db, clinic, "B", utm_source="facebook", utm_campaign="hifu")
    _visit(db, clinic, b, revenue=6000000)

    rows = funnel.build(db, clinic["clinic"].id, by_campaign=True).channels
    assert {r.campaign for r in rows} == {"pico", "hifu"}
    assert rows[0].campaign == "hifu"

    merged = funnel.build(db, clinic["clinic"].id, by_campaign=False).channels
    assert len(merged) == 1 and merged[0].revenue == 8000000


def test_revenue_per_lead_is_what_compares_against_ad_cost(db, clinic):
    for i in range(4):
        p = _lead(db, clinic, f"K{i}", utm_source="facebook")
        if i == 0:
            _visit(db, clinic, p, revenue=8000000)

    row = funnel.build(db, clinic["clinic"].id).channels[0]
    assert row.revenue_per_lead == 2000000


def test_an_empty_period_reports_zero_rather_than_failing(db, clinic):
    f = funnel.build(db, clinic["clinic"].id)
    assert f.leads == 0 and f.channels == [] and f.lead_to_booking == 0.0


def test_another_clinics_patients_are_invisible(db, clinic):
    other = Clinic(name="Khac", is_active=True)
    db.add(other)
    db.flush()
    db.add(PatientLead(clinic_id=other.id, full_name="Nguoi khac", consent_given=True,
                       utm_source="facebook",
                       first_seen_at=datetime.datetime.now()))
    db.commit()

    assert funnel.build(db, clinic["clinic"].id).leads == 0


# --- latest touch: kept, but never allowed to claim credit --------------------

def test_latest_touch_records_the_return_visit(db):
    first = FakeResponse()
    attribution.remember(FakeRequest(params={"utm_source": "facebook",
                                             "utm_campaign": "pico-thang-8"}), first)

    second = FakeResponse()
    stored = attribution.remember(
        FakeRequest(params={"utm_source": "google", "utm_medium": "organic"},
                    cookies={attribution.COOKIE_NAME: first.cookies[attribution.COOKIE_NAME]}),
        second)

    assert stored["first"]["utm_source"] == "facebook"
    assert stored["latest"]["utm_source"] == "google"


def test_a_lead_carries_both_touches(db, clinic):
    first = FakeResponse()
    attribution.remember(FakeRequest(params={"utm_source": "facebook",
                                             "utm_campaign": "pico-thang-8"}), first)
    second = FakeResponse()
    stored = attribution.remember(
        FakeRequest(path="/book/caredesk/dat-lich",
                    params={"utm_source": "google", "utm_campaign": "retarget"},
                    cookies={attribution.COOKIE_NAME: first.cookies[attribution.COOKIE_NAME]}),
        second)

    patient = PatientLead(clinic_id=clinic["clinic"].id, full_name="Hai diem cham",
                          consent_given=True)
    attribution.apply_to_lead(patient, stored)

    assert patient.utm_source == "facebook"
    assert patient.utm_campaign == "pico-thang-8"
    assert patient.latest_utm_source == "google"
    assert patient.latest_utm_campaign == "retarget"
    assert patient.touch_count == 2


def test_the_channel_report_ignores_latest_touch(db, clinic):
    """The whole reason the two are stored separately."""
    patient = _lead(db, clinic, "Retarget", utm_source="facebook",
                    latest_utm_source="google")
    _visit(db, clinic, patient, revenue=4000000)

    row = funnel.build(db, clinic["clinic"].id).channels[0]
    assert row.channel == "facebook", "công thuộc về kênh tìm ra khách"


def test_a_direct_return_visit_does_not_erase_the_campaign(db):
    first = FakeResponse()
    attribution.remember(FakeRequest(params={"utm_source": "tiktok"}), first)

    second = FakeResponse()
    stored = attribution.remember(
        FakeRequest(path="/book/caredesk/bach-mai",
                    cookies={attribution.COOKIE_NAME: first.cookies[attribution.COOKIE_NAME]}),
        second)

    assert stored["first"]["utm_source"] == "tiktok"
    assert stored["latest"]["utm_source"] == "tiktok"
    assert stored["latest"]["landing_path"] == "/book/caredesk/bach-mai"
    assert stored["touches"] == 2


def test_an_old_flat_cookie_still_works(db, clinic):
    """Cookies written before latest-touch existed are already in browsers."""
    import json
    flat = json.dumps({"utm_source": "facebook", "utm_campaign": "cu",
                       "first_seen_at": "2026-08-01T10:00:00"})

    patient = PatientLead(clinic_id=clinic["clinic"].id, full_name="Cookie cu",
                          consent_given=True)
    attribution.apply_to_lead(patient, json.loads(flat))

    assert patient.utm_source == "facebook"
    assert patient.utm_campaign == "cu"


# --- confirmation speed --------------------------------------------------------

def test_confirmation_speed_separates_a_slow_desk_from_a_weak_channel(db, clinic):
    """"Facebook is underperforming" and "we take four hours to ring back" look
    identical in a conversion rate and need opposite fixes."""
    now = datetime.datetime.now()
    for minutes in (5, 15, 240):
        patient = _lead(db, clinic, f"K{minutes}", utm_source="facebook")
        appt = _visit(db, clinic, patient, status="confirmed")
        appt.booking_requested_at = now - datetime.timedelta(minutes=minutes)
        appt.booking_confirmed_at = now
    db.commit()

    speed = funnel.confirmation_speed(db, clinic["clinic"].id)
    assert speed["requested"] == 3
    assert speed["confirmed"] == 3
    assert speed["median_minutes"] == 15, "trung vị, không phải trung bình"
    assert speed["over_1h"] == 1


def test_an_unconfirmed_request_lowers_the_confirm_rate(db, clinic):
    now = datetime.datetime.now()
    patient = _lead(db, clinic, "Chua goi lai", utm_source="facebook")
    appt = _visit(db, clinic, patient, status="pending")
    appt.booking_requested_at = now - datetime.timedelta(hours=3)
    db.commit()

    speed = funnel.confirmation_speed(db, clinic["clinic"].id)
    assert speed["requested"] == 1 and speed["confirmed"] == 0
    assert speed["confirm_rate_percent"] == 0.0


def test_confirmation_speed_on_an_empty_period(db, clinic):
    speed = funnel.confirmation_speed(db, clinic["clinic"].id)
    assert speed["requested"] == 0 and speed["median_minutes"] is None
