import datetime
import logging
import secrets
from sqlalchemy.orm import Session
from backend.app.core.config import settings
from backend.app.core.database import SessionLocal
from backend.app.models.models import (
    User, Clinic, Branch, Service, Doctor, WorkingSchedule, AISafetyRule, Organization, Plan
)
from backend.app.core.roles import ROLE_PLATFORM
from backend.app.core.slug import assign_slug
from backend.app.core.security import get_password_hash

logger = logging.getLogger(__name__)


def _seed_demo_data(db: Session) -> None:
    """Demo accounts + demo clinic + demo chain. Dev/local convenience only —
    gated behind settings.SEED_DEMO_DATA so a fresh production DB never gets
    seeded with these publicly-known credentials or fake business data."""

    # 1. Seed Users
    if db.query(User).count() == 0:
        logger.info("Seeding demo users...")
        users = [
            User(
                email="owner@caredesk.ai",
                password_hash=get_password_hash("owner123"),
                full_name="Chủ phòng khám Nguyễn Văn Chủ",
                role="owner",
                is_active=True
            ),
            User(
                email="receptionist@caredesk.ai",
                password_hash=get_password_hash("receptionist123"),
                full_name="Lễ tân Lê Thị Lễ",
                role="receptionist",
                is_active=True
            )
        ]
        db.add_all(users)
        db.commit()

    # 2. Seed Clinic
    if db.query(Clinic).count() == 0:
        logger.info("Seeding demo clinic...")
        clinic = Clinic(
            name="Phòng khám Da liễu Thẩm mỹ CareDesk",
            logo_url="https://images.unsplash.com/photo-1629909613654-28e377c37b09?w=150",
            phone="0901234567",
            address="123 Đường Ba Tháng Hai, Quận 10, TP. Hồ Chí Minh",
            cancellation_policy="Khách hàng vui lòng hủy hoặc đổi lịch hẹn trước ít nhất 2 giờ so với giờ khám dự kiến. Sau thời gian này, lịch hẹn sẽ được tính là No-Show (Vắng mặt)."
        )
        db.add(clinic)
        db.commit()

        # 3. Seed Branches
        logger.info("Seeding demo branches...")
        branch1 = Branch(
            clinic_id=clinic.id,
            name="Chi nhánh Quận 10 (Trụ sở chính)",
            address="123 Đường Ba Tháng Hai, Quận 10, TP. Hồ Chí Minh",
            phone="0287300123",
            working_hours="08:00 - 20:00"
        )
        branch2 = Branch(
            clinic_id=clinic.id,
            name="Chi nhánh Quận 1",
            address="456 Đường Nguyễn Huệ, Quận 1, TP. Hồ Chí Minh",
            phone="0287300456",
            working_hours="09:00 - 21:00"
        )
        db.add_all([branch1, branch2])
        db.commit()

        # 4. Seed Services
        logger.info("Seeding demo services...")
        services = [
            Service(
                clinic_id=clinic.id,
                name="Khám da liễu với Bác sĩ chuyên khoa",
                description="Khám lâm sàng, soi da kỹ thuật số trực tiếp với Bác sĩ chuyên khoa I trở lên để xác định tình trạng mụn, nám, tàn nhang, sẹo hoặc viêm da.",
                price=150000,
                duration_minutes=30,
                preparation_instructions="Vui lòng tẩy trang và rửa sạch mặt trước giờ khám 10 phút. Mang theo đơn thuốc hoặc các sản phẩm dưỡng da đang sử dụng.",
                faq_data=[
                    {"question": "Khám da liễu có đắt không?", "answer": "Chi phí khám da liễu với bác sĩ chuyên khoa tại CareDesk là 150,000đ. Đã bao gồm soi da bằng máy chuyên dụng."},
                    {"question": "Thời gian khám mất bao lâu?", "answer": "Một ca khám và tư vấn chi tiết thường kéo dài khoảng 20 - 30 phút."}
                ]
            ),
            Service(
                clinic_id=clinic.id,
                name="Điều trị mụn Chuẩn Y Khoa",
                description="Quy trình 12 bước điều trị mụn bao gồm tẩy trang, rửa mặt, xông hơi, hút bã nhờn, lấy nhân mụn vô trùng, đi điện di kháng viêm và chiếu ánh sáng sinh học Biolight giảm sưng đỏ.",
                price=450000,
                duration_minutes=75,
                preparation_instructions="Không tự ý nặn mụn ở nhà trước khi đi trị liệu. Hạn chế trang điểm đậm trước khi thực hiện dịch vụ.",
                faq_data=[
                    {"question": "Điều trị mụn có đau không?", "answer": "Quá trình lấy nhân mụn sẽ có cảm giác châm chích nhẹ, tuy nhiên kỹ thuật viên của phòng khám đã được đào tạo tay nghề cao giúp giảm thiểu tối đa cảm giác đau rát. Sau đó bạn sẽ được chiếu ánh sáng giảm sưng."},
                    {"question": "Có cần nghỉ dưỡng sau trị mụn không?", "answer": "Sau khi lấy nhân mụn, da có thể hơi ửng đỏ nhẹ trong vòng 1-2 tiếng đầu. Bạn có thể sinh hoạt bình thường nhưng cần tránh ánh nắng trực tiếp và sử dụng kem chống nắng dịu nhẹ."}
                ]
            ),
            Service(
                clinic_id=clinic.id,
                name="Laser Fractional CO2 trị sẹo rỗ",
                description="Sử dụng công nghệ Laser Fractional CO2 tạo tổn thương vi điểm giả lập để kích thích tăng sinh Collagen tự thân, lấp đầy sẹo rỗ, se khít lỗ chân lông và làm đều màu da.",
                price=1200000,
                duration_minutes=60,
                preparation_instructions="Tránh tiếp xúc ánh nắng cường độ cao trước trị liệu 3 ngày. Không sử dụng các sản phẩm chứa Retinol/Tretinoin trước 5 ngày.",
                faq_data=[
                    {"question": "Trị sẹo bằng Laser CO2 có hiệu quả không?", "answer": "Công nghệ Fractional CO2 mang lại hiệu quả cải thiện sẹo rỗ từ 50-80% sau một liệu trình từ 3-5 buổi, tùy thuộc vào cơ địa và độ sâu của sẹo."},
                    {"question": "Chăm sóc da sau khi bắn Laser như thế nào?", "answer": "Trong 24h đầu, chỉ rửa mặt bằng nước muối sinh lý. Từ ngày thứ 2 sử dụng serum phục hồi và kem chống nắng tuyệt đối. Da sẽ bong vảy nhẹ tự nhiên sau 3-5 ngày, không tự ý cạy vảy."}
                ]
            )
        ]
        db.add_all(services)
        db.commit()

        # 5. Seed Doctors
        logger.info("Seeding demo doctors...")
        doc1 = Doctor(name="Bác sĩ Nguyễn Văn A", specialty="Chuyên khoa Da liễu / Trị sẹo", branch_id=branch1.id, is_active=True)
        doc2 = Doctor(name="Bác sĩ Lê Thị B", specialty="Thẩm mỹ da / Điều trị mụn", branch_id=branch1.id, is_active=True)
        doc3 = Doctor(name="Bác sĩ Trần Minh C", specialty="Chuyên khoa Da liễu", branch_id=branch2.id, is_active=True)
        db.add_all([doc1, doc2, doc3])
        db.commit()

        # 6. Seed WorkingSchedules
        logger.info("Seeding demo schedules...")
        # Doctor A works Monday (0) to Friday (4) from 08:00 to 12:00 and 13:30 to 17:30 in Branch 1
        for day in range(5):
            db.add(WorkingSchedule(
                doctor_id=doc1.id, branch_id=branch1.id, day_of_week=day,
                start_time=datetime.time(8, 0), end_time=datetime.time(12, 0)
            ))
            db.add(WorkingSchedule(
                doctor_id=doc1.id, branch_id=branch1.id, day_of_week=day,
                start_time=datetime.time(13, 30), end_time=datetime.time(17, 30)
            ))
        # Doctor B works Saturday (5) & Sunday (6) from 09:00 to 18:00
        for day in [5, 6]:
            db.add(WorkingSchedule(
                doctor_id=doc2.id, branch_id=branch1.id, day_of_week=day,
                start_time=datetime.time(9, 0), end_time=datetime.time(18, 0)
            ))
        db.commit()

    # 7. Multi-tenant backfill: bind seeded users & doctors to the demo clinic
    # (Pro plan). Demo-only — unsafe against real multi-tenant data, since it
    # force-assigns any unclaimed clinic_id=NULL user/doctor to whichever
    # clinic happens to be id=1.
    clinic = db.query(Clinic).order_by(Clinic.id.asc()).first()
    if clinic:
        # Only bind the demo clinic's OWN staff. Never touch platform admins or
        # chain owners — their clinic_id is intentionally NULL (runs every startup).
        db.query(User).filter(
            User.clinic_id == None,              # noqa: E711
            User.is_platform_admin == False,     # noqa: E712
            User.organization_id == None,        # noqa: E711
        ).update({User.clinic_id: clinic.id}, synchronize_session=False)
        db.query(Doctor).filter(Doctor.clinic_id == None).update({Doctor.clinic_id: clinic.id})  # noqa: E711
        if clinic.plan != "pro":
            clinic.plan = "pro"
            clinic.ai_quota_monthly = settings.PLAN_PRO_QUOTA
        if not clinic.monthly_fee:
            clinic.monthly_fee = 1500000  # demo Pro fee, feeds the ROI metric
        db.commit()

        # 8. Default revenue automations (follow-up, recall, review, waitlist...)
        from backend.app.services.events import seed_default_automations
        seed_default_automations(db, clinic.id)

    # 9. Demo chain: attach the demo clinic to an Organization + a chain-owner account
    if db.query(Organization).count() == 0:
        logger.info("Seeding demo Organization (chain)...")
        org = Organization(name="Chuỗi Thẩm mỹ CareDesk Group", is_active=True)
        db.add(org)
        db.flush()
        demo_clinic = db.query(Clinic).order_by(Clinic.id.asc()).first()
        if demo_clinic and demo_clinic.organization_id is None:
            demo_clinic.organization_id = org.id
        db.add(User(
            organization_id=org.id, clinic_id=None,
            email="chain@caredesk.ai",
            password_hash=get_password_hash("chain123"),
            full_name="Chủ chuỗi Trần Thị Chuỗi",
            role="org_owner",
            is_active=True,
        ))
        db.commit()


def _seed_platform_admin(db: Session) -> None:
    """Vendor/publisher super-admin — idempotent, always seeded (every
    environment needs at least one account able to reach /platform)."""
    if db.query(User).filter(User.is_platform_admin == True).count() > 0:  # noqa: E712
        return

    email = settings.PLATFORM_ADMIN_EMAIL or "platform@caredesk.ai"
    password = settings.PLATFORM_ADMIN_PASSWORD
    generated = False
    if not password:
        if settings.is_production:
            password = secrets.token_urlsafe(18)
            generated = True
        else:
            password = "platform123"

    logger.info("Seeding platform super-admin account...")
    db.add(User(
        email=email,
        password_hash=get_password_hash(password),
        full_name="Nhà phát hành CareDesk",
        role=ROLE_PLATFORM,
        is_platform_admin=True,
        clinic_id=None,
        is_active=True,
    ))
    db.commit()

    if generated:
        logger.warning(
            "No PLATFORM_ADMIN_PASSWORD set - generated a random password for "
            "%s (shown once, not stored anywhere else): %s "
            "Log in and change it immediately, or set PLATFORM_ADMIN_EMAIL / "
            "PLATFORM_ADMIN_PASSWORD before next deploy.",
            email, password,
        )


def seed_db() -> None:
    db: Session = SessionLocal()
    try:
        if settings.SEED_DEMO_DATA:
            _seed_demo_data(db)

        # Reference data below is safe (and required) in every environment.

        # AI safety rules — global, not clinic-scoped
        if db.query(AISafetyRule).count() == 0:
            logger.info("Seeding AI safety rules...")
            rules = [
                AISafetyRule(
                    category="urgent",
                    keyword_pattern="đau dữ dội,khó thở,sưng mặt dữ dội,chảy máu nhiều,sốt cao,co giật,phản ứng phản vệ",
                    fallback_message="Tôi nhận thấy triệu chứng của bạn có thể là tình trạng cần cấp cứu khẩn cấp. Tôi đang lập tức chuyển thông tin của bạn cho Lễ tân/Bác sĩ hỗ trợ. Vui lòng gọi ngay Hotline cấp cứu phòng khám: 0901234567 hoặc đến ngay bệnh viện/cơ sở y tế gần nhất!",
                    force_handoff=True
                ),
                AISafetyRule(
                    category="clinical_diagnosis",
                    keyword_pattern="bệnh gì,kê đơn,uống thuốc gì,chữa khỏi không,ngừng thuốc,uống thuốc nào,tôi bị bệnh gì",
                    fallback_message="CareDesk AI chỉ hỗ trợ đặt lịch hẹn và giải đáp thông tin dịch vụ hành chính của phòng khám. Tôi không có chuyên môn để chẩn đoán bệnh hoặc kê đơn thuốc. Tôi đã ghi nhận câu hỏi và chuyển thông tin đến Bác sĩ chuyên khoa để tư vấn cho bạn sớm nhất.",
                    force_handoff=True
                ),
                AISafetyRule(
                    category="clinical_image",
                    keyword_pattern="xem ảnh da,đây là bệnh gì,xem giúp tấm ảnh,ảnh chụp da,nhìn ảnh này",
                    fallback_message="Tôi là trợ lý ảo và không thể phân tích hình ảnh da hoặc chẩn đoán qua ảnh chụp. Vui lòng đặt lịch hẹn trực tiếp hoặc gửi thông tin để tôi chuyển cho bác sĩ xem xét trực tiếp trên hồ sơ của bạn.",
                    force_handoff=True
                ),
                AISafetyRule(
                    category="sensitive_groups",
                    keyword_pattern="mang thai,có thai,bầu,bà bầu,cho con bú,trẻ em,trẻ sơ sinh,dị ứng thuốc,phản ứng phụ",
                    fallback_message="Đối với các trường hợp đặc biệt như phụ nữ có thai/cho con bú, trẻ em hoặc khách hàng có tiền sử dị ứng thuốc, chúng tôi cần bác sĩ chuyên khoa trực tiếp thăm khám kỹ lưỡng. Tôi xin chuyển tiếp cuộc gọi đến lễ tân để liên hệ hỗ trợ riêng cho bạn.",
                    force_handoff=True
                )
            ]
            db.add_all(rules)
            db.commit()

        _seed_platform_admin(db)

        # Subscription plan catalogue (idempotent)
        if db.query(Plan).count() == 0:
            logger.info("Seeding plan catalogue...")
            db.add_all([
                Plan(code="free", name="Gói Free", monthly_quota=settings.PLAN_FREE_QUOTA,
                     price=0, trial_days=0, is_active=True),
                Plan(code="pro", name="Gói Pro (Dùng thử 14 ngày)", monthly_quota=settings.PLAN_PRO_QUOTA,
                     price=1500000, trial_days=14, is_active=True),
            ])
            db.commit()

        # Backfill slugs + link clinics to plan rows (idempotent).
        # assign_slug is a no-op once an entity has a slug, so this never churns
        # a published URL.
        for org in db.query(Organization).all():
            assign_slug(db, org)
        for c in db.query(Clinic).all():
            assign_slug(db, c)
            if c.plan_id is None:
                plan = db.query(Plan).filter(Plan.code == (c.plan or "free")).first()
                if plan:
                    c.plan_id = plan.id
        for b in db.query(Branch).all():
            assign_slug(db, b)
        db.commit()

        logger.info("Database seeding completed.")
    except Exception:
        logger.exception("Error during seeding")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_db()
