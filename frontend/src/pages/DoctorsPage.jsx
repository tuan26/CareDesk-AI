import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { API_BASE } from '../api';

const DAY_NAMES = ['Thứ 2', 'Thứ 3', 'Thứ 4', 'Thứ 5', 'Thứ 6', 'Thứ 7', 'Chủ nhật'];

const EMPTY_DOCTOR_FORM = { name: '', specialty: '', branch_id: '', is_active: true };
const EMPTY_SCHEDULE_FORM = { doctor_id: '', branch_id: '', day_of_week: 0, start_time: '08:00', end_time: '17:00' };

export default function DoctorsPage() {
  const [doctors, setDoctors] = useState([]);
  const [branches, setBranches] = useState([]);
  const [schedules, setSchedules] = useState([]);
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showDoctorModal, setShowDoctorModal] = useState(false);
  const [editingDoctor, setEditingDoctor] = useState(null);
  const [doctorForm, setDoctorForm] = useState(EMPTY_DOCTOR_FORM);
  const [timeOff, setTimeOff] = useState([]);
  const [offForm, setOffForm] = useState({ doctor_id: '', start_date: '', end_date: '', start_time: '', end_time: '', reason: '' });
  const [offError, setOffError] = useState('');
  const [showScheduleModal, setShowScheduleModal] = useState(false);
  const [scheduleForm, setScheduleForm] = useState(EMPTY_SCHEDULE_FORM);
  const navigate = useNavigate();

  const getHeaders = () => {
    const token = localStorage.getItem('caredesk_token');
    return {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    };
  };

  const isManager = user && user.role === 'owner';

  const fetchData = async () => {
    try {
      const headers = getHeaders();
      const [meRes, doctorsRes, branchesRes, schedulesRes, offRes] = await Promise.all([
        fetch(`${API_BASE}/auth/me`, { headers }),
        fetch(`${API_BASE}/clinic/doctors`, { headers }),
        fetch(`${API_BASE}/clinic/branches`, { headers }),
        fetch(`${API_BASE}/clinic/schedules`, { headers }),
        fetch(`${API_BASE}/clinic/time-off`, { headers })
      ]);
      if (meRes.status === 401 || doctorsRes.status === 401) throw new Error('Unauthorized');

      setUser(await meRes.json());
      setDoctors(await doctorsRes.json());
      setBranches(await branchesRes.json());
      setSchedules(await schedulesRes.json());
      if (offRes.ok) setTimeOff(await offRes.json());
    } catch (err) {
      console.error(err);
      if (err.message === 'Unauthorized') {
        localStorage.removeItem('caredesk_token');
        navigate('/login');
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [navigate]);

  const branchName = (branchId) => branches.find(b => b.id === branchId)?.name || '—';
  const doctorName = (doctorId) => doctors.find(d => d.id === doctorId)?.name || '—';
  const formatTime = (t) => (t || '').substring(0, 5); // "08:00:00" -> "08:00"

  // --- Doctor CRUD ---
  const openCreateDoctor = () => {
    setEditingDoctor(null);
    setDoctorForm({ ...EMPTY_DOCTOR_FORM, branch_id: branches[0]?.id || '' });
    setShowDoctorModal(true);
  };

  const openEditDoctor = (doctor) => {
    setEditingDoctor(doctor);
    setDoctorForm({
      name: doctor.name,
      specialty: doctor.specialty || '',
      branch_id: doctor.branch_id || '',
      is_active: doctor.is_active
    });
    setShowDoctorModal(true);
  };

  const handleSubmitDoctor = async (e) => {
    e.preventDefault();
    const payload = {
      name: doctorForm.name,
      specialty: doctorForm.specialty || null,
      branch_id: doctorForm.branch_id ? parseInt(doctorForm.branch_id, 10) : null,
      is_active: doctorForm.is_active
    };
    const url = editingDoctor
      ? `${API_BASE}/clinic/doctors/${editingDoctor.id}`
      : `${API_BASE}/clinic/doctors`;

    try {
      const response = await fetch(url, {
        method: editingDoctor ? 'PUT' : 'POST',
        headers: getHeaders(),
        body: JSON.stringify(payload)
      });
      if (response.ok) {
        setShowDoctorModal(false);
        fetchData();
      } else {
        const data = await response.json().catch(() => null);
        alert(data?.detail || 'Không thể lưu thông tin bác sĩ.');
      }
    } catch (err) {
      console.error(err);
      alert('Lỗi kết nối máy chủ.');
    }
  };

  const handleDeleteDoctor = async (doctor) => {
    if (!window.confirm(`Bạn có chắc muốn xóa "${doctor.name}"?\nToàn bộ lịch làm việc của bác sĩ này cũng sẽ bị xóa.`)) return;
    try {
      const response = await fetch(`${API_BASE}/clinic/doctors/${doctor.id}`, {
        method: 'DELETE',
        headers: getHeaders()
      });
      if (response.ok || response.status === 204) {
        fetchData();
      } else {
        const data = await response.json().catch(() => null);
        alert(data?.detail || 'Không thể xóa bác sĩ.');
      }
    } catch (err) {
      console.error(err);
      alert('Lỗi kết nối máy chủ.');
    }
  };

  // --- Schedule CRUD ---
  const openCreateSchedule = () => {
    setScheduleForm({
      ...EMPTY_SCHEDULE_FORM,
      doctor_id: doctors[0]?.id || '',
      branch_id: branches[0]?.id || ''
    });
    setShowScheduleModal(true);
  };

  const handleSubmitSchedule = async (e) => {
    e.preventDefault();
    if (scheduleForm.start_time >= scheduleForm.end_time) {
      alert('Giờ bắt đầu phải nhỏ hơn giờ kết thúc.');
      return;
    }
    const payload = {
      doctor_id: parseInt(scheduleForm.doctor_id, 10),
      branch_id: parseInt(scheduleForm.branch_id, 10),
      day_of_week: parseInt(scheduleForm.day_of_week, 10),
      start_time: scheduleForm.start_time,
      end_time: scheduleForm.end_time
    };
    try {
      const response = await fetch(`${API_BASE}/clinic/schedules`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify(payload)
      });
      if (response.ok) {
        setShowScheduleModal(false);
        fetchData();
      } else {
        const data = await response.json().catch(() => null);
        alert(data?.detail || 'Không thể thêm lịch làm việc.');
      }
    } catch (err) {
      console.error(err);
      alert('Lỗi kết nối máy chủ.');
    }
  };

  const handleDeleteSchedule = async (sched) => {
    if (!window.confirm(`Xóa ca làm việc ${DAY_NAMES[sched.day_of_week]} (${formatTime(sched.start_time)} - ${formatTime(sched.end_time)}) của ${doctorName(sched.doctor_id)}?`)) return;
    try {
      const response = await fetch(`${API_BASE}/clinic/schedules/${sched.id}`, {
        method: 'DELETE',
        headers: getHeaders()
      });
      if (response.ok || response.status === 204) {
        fetchData();
      } else {
        const data = await response.json().catch(() => null);
        alert(data?.detail || 'Không thể xóa lịch làm việc.');
      }
    } catch (err) {
      console.error(err);
      alert('Lỗi kết nối máy chủ.');
    }
  };

  const sortedSchedules = [...schedules].sort((a, b) =>
    a.doctor_id - b.doctor_id || a.day_of_week - b.day_of_week || a.start_time.localeCompare(b.start_time)
  );

  if (loading) return <div style={{ padding: '24px', textAlign: 'center' }}>Đang tải danh sách bác sĩ...</div>;

  const saveTimeOff = async (e) => {
    e.preventDefault();
    setOffError('');
    const body = {
      doctor_id: offForm.doctor_id ? Number(offForm.doctor_id) : null,
      start_date: offForm.start_date,
      end_date: offForm.end_date || offForm.start_date,
      start_time: offForm.start_time || null,
      end_time: offForm.end_time || null,
      reason: offForm.reason || null,
    };
    const res = await fetch(`${API_BASE}/clinic/time-off`, {
      method: 'POST', headers: getHeaders(), body: JSON.stringify(body),
    });
    if (!res.ok) {
      setOffError((await res.json()).detail || 'Không lưu được lịch nghỉ.');
      return;
    }
    setOffForm({ doctor_id: '', start_date: '', end_date: '', start_time: '', end_time: '', reason: '' });
    fetchData();
  };

  const deleteTimeOff = async (id) => {
    if (!window.confirm('Xoá lịch nghỉ này? Các khung giờ sẽ mở lại cho khách đặt.')) return;
    await fetch(`${API_BASE}/clinic/time-off/${id}`, { method: 'DELETE', headers: getHeaders() });
    fetchData();
  };

  return (
    <div>
      <div className="page-header">
        <div className="page-title">
          <h1>Bác sĩ & Lịch làm việc</h1>
          <p>Quản lý đội ngũ bác sĩ và ca làm việc trong tuần. AI dựa vào lịch này để đề xuất khung giờ trống.</p>
        </div>
        {isManager && (
          <div style={{ display: 'flex', gap: '12px' }}>
            <button className="btn btn-secondary" onClick={openCreateSchedule} disabled={doctors.length === 0}>+ Thêm ca làm việc</button>
            <button className="btn btn-primary" onClick={openCreateDoctor}>+ Thêm bác sĩ</button>
          </div>
        )}
      </div>

      {/* Bảng bác sĩ */}
      <div className="card-table-wrapper">
        <div className="card-header">
          <h2>Đội ngũ bác sĩ ({doctors.length})</h2>
        </div>
        {doctors.length === 0 ? (
          <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)' }}>Chưa có bác sĩ nào.</div>
        ) : (
          <table className="custom-table">
            <thead>
              <tr>
                <th>Bác sĩ</th>
                <th>Chuyên khoa</th>
                <th>Chi nhánh</th>
                <th>Trạng thái</th>
                {isManager && <th style={{ width: '140px' }}>Thao tác</th>}
              </tr>
            </thead>
            <tbody>
              {doctors.map((doctor) => (
                <tr key={doctor.id}>
                  <td style={{ fontWeight: 600 }}>{doctor.name}</td>
                  <td>{doctor.specialty || '—'}</td>
                  <td>{branchName(doctor.branch_id)}</td>
                  <td>
                    <span className={`badge ${doctor.is_active ? 'completed' : 'cancelled'}`}>
                      {doctor.is_active ? 'Đang làm việc' : 'Tạm nghỉ'}
                    </span>
                  </td>
                  {isManager && (
                    <td>
                      <div style={{ display: 'flex', gap: '8px' }}>
                        <button className="btn btn-secondary btn-sm" onClick={() => openEditDoctor(doctor)}>Sửa</button>
                        <button className="btn btn-danger btn-sm" onClick={() => handleDeleteDoctor(doctor)}>Xóa</button>
                      </div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Bảng lịch làm việc */}
      <div className="card-table-wrapper">
        <div className="card-header">
          <h2>Ca làm việc trong tuần ({schedules.length})</h2>
        </div>
        {schedules.length === 0 ? (
          <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)' }}>Chưa có ca làm việc nào được xếp.</div>
        ) : (
          <table className="custom-table">
            <thead>
              <tr>
                <th>Bác sĩ</th>
                <th>Ngày trong tuần</th>
                <th>Khung giờ</th>
                <th>Chi nhánh</th>
                {isManager && <th style={{ width: '80px' }}></th>}
              </tr>
            </thead>
            <tbody>
              {sortedSchedules.map((sched) => (
                <tr key={sched.id}>
                  <td style={{ fontWeight: 600 }}>{doctorName(sched.doctor_id)}</td>
                  <td>{DAY_NAMES[sched.day_of_week]}</td>
                  <td>{formatTime(sched.start_time)} - {formatTime(sched.end_time)}</td>
                  <td>{branchName(sched.branch_id)}</td>
                  {isManager && (
                    <td>
                      <button className="btn btn-danger btn-sm" onClick={() => handleDeleteSchedule(sched)}>Xóa</button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Ngày nghỉ — ngoại lệ của lịch tuần ở trên.
          Không có phần này thì AI vẫn nhận lịch vào ngày bác sĩ nghỉ phép hoặc
          ngày phòng khám đóng cửa, và khách đến nơi không có ai. */}
      <div className="card-table-wrapper">
        <div className="card-header">
          <h2>Ngày nghỉ ({timeOff.length})</h2>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            Nghỉ phép, nghỉ lễ, nghỉ nửa buổi. AI sẽ không nhận lịch trong các khoảng này.
          </span>
        </div>

        {isManager && (
          <form onSubmit={saveTimeOff} style={{ padding: '14px 20px', borderBottom: '1px solid var(--border-color)', display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
            <div className="form-group" style={{ margin: 0, minWidth: 170 }}>
              <label style={{ fontSize: 12 }}>Ai nghỉ</label>
              <select className="form-control" value={offForm.doctor_id}
                onChange={(e) => setOffForm({ ...offForm, doctor_id: e.target.value })}>
                <option value="">Cả phòng khám (nghỉ lễ)</option>
                {doctors.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </div>
            <div className="form-group" style={{ margin: 0 }}>
              <label style={{ fontSize: 12 }}>Từ ngày *</label>
              <input className="form-control" type="date" required value={offForm.start_date}
                onChange={(e) => setOffForm({ ...offForm, start_date: e.target.value })} />
            </div>
            <div className="form-group" style={{ margin: 0 }}>
              <label style={{ fontSize: 12 }}>Đến ngày</label>
              <input className="form-control" type="date" value={offForm.end_date}
                onChange={(e) => setOffForm({ ...offForm, end_date: e.target.value })} />
            </div>
            <div className="form-group" style={{ margin: 0 }}>
              <label style={{ fontSize: 12 }}>Từ giờ</label>
              <input className="form-control" type="time" value={offForm.start_time}
                onChange={(e) => setOffForm({ ...offForm, start_time: e.target.value })} />
            </div>
            <div className="form-group" style={{ margin: 0 }}>
              <label style={{ fontSize: 12 }}>Đến giờ</label>
              <input className="form-control" type="time" value={offForm.end_time}
                onChange={(e) => setOffForm({ ...offForm, end_time: e.target.value })} />
            </div>
            <div className="form-group" style={{ margin: 0, flex: 1, minWidth: 140 }}>
              <label style={{ fontSize: 12 }}>Lý do</label>
              <input className="form-control" placeholder="vd. Nghỉ Tết" value={offForm.reason}
                onChange={(e) => setOffForm({ ...offForm, reason: e.target.value })} />
            </div>
            <button className="btn btn-primary" type="submit">Thêm</button>
            <div style={{ flexBasis: '100%', fontSize: 12, color: 'var(--text-muted)' }}>
              Bỏ trống giờ = nghỉ cả ngày. Bỏ trống "đến ngày" = nghỉ đúng một ngày.
            </div>
            {offError && <div style={{ flexBasis: '100%', color: '#b91c1c', fontSize: 13 }}>{offError}</div>}
          </form>
        )}

        {timeOff.length === 0 ? (
          <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)' }}>
            Chưa khai ngày nghỉ nào. Nhớ khai trước các dịp nghỉ lễ.
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr><th>Ai</th><th>Thời gian</th><th>Lý do</th>{isManager && <th></th>}</tr>
            </thead>
            <tbody>
              {timeOff.map((o) => (
                <tr key={o.id}>
                  <td>{o.doctor_name}</td>
                  <td>
                    {o.start_date === o.end_date ? o.start_date : `${o.start_date} → ${o.end_date}`}
                    {o.start_time && <span style={{ color: 'var(--text-muted)' }}> ({o.start_time.slice(0, 5)}–{o.end_time.slice(0, 5)})</span>}
                    {!o.start_time && <span style={{ color: 'var(--text-muted)' }}> (cả ngày)</span>}
                  </td>
                  <td>{o.reason || '—'}</td>
                  {isManager && (
                    <td style={{ textAlign: 'right' }}>
                      <button className="btn btn-secondary btn-sm" onClick={() => deleteTimeOff(o.id)}>Xoá</button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Modal Thêm/Sửa bác sĩ */}
      {showDoctorModal && (
        <div className="modal-overlay" onClick={() => setShowDoctorModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>{editingDoctor ? 'Chỉnh sửa bác sĩ' : 'Thêm bác sĩ mới'}</h3>
              <button className="modal-close-btn" onClick={() => setShowDoctorModal(false)}>&times;</button>
            </div>
            <form onSubmit={handleSubmitDoctor}>
              <div className="modal-body">
                <div className="form-group">
                  <label>Họ tên bác sĩ *</label>
                  <input
                    className="form-control"
                    value={doctorForm.name}
                    onChange={(e) => setDoctorForm({ ...doctorForm, name: e.target.value })}
                    placeholder="Bác sĩ Nguyễn Văn A"
                    required
                  />
                </div>
                <div className="form-group">
                  <label>Chuyên khoa</label>
                  <input
                    className="form-control"
                    value={doctorForm.specialty}
                    onChange={(e) => setDoctorForm({ ...doctorForm, specialty: e.target.value })}
                    placeholder="Chuyên khoa Da liễu / Trị sẹo"
                  />
                </div>
                <div className="form-group">
                  <label>Chi nhánh công tác</label>
                  <select
                    className="form-control"
                    value={doctorForm.branch_id}
                    onChange={(e) => setDoctorForm({ ...doctorForm, branch_id: e.target.value })}
                  >
                    <option value="">— Chưa phân bổ —</option>
                    {branches.map((b) => (
                      <option key={b.id} value={b.id}>{b.name}</option>
                    ))}
                  </select>
                </div>
                <div className="form-group" style={{ marginBottom: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <input
                    type="checkbox"
                    id="doctor-active"
                    checked={doctorForm.is_active}
                    onChange={(e) => setDoctorForm({ ...doctorForm, is_active: e.target.checked })}
                  />
                  <label htmlFor="doctor-active" style={{ marginBottom: 0, textTransform: 'none', fontSize: '14px' }}>
                    Đang làm việc (hiển thị khi đặt lịch)
                  </label>
                </div>
              </div>
              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick={() => setShowDoctorModal(false)}>Hủy</button>
                <button type="submit" className="btn btn-primary">{editingDoctor ? 'Lưu thay đổi' : 'Thêm bác sĩ'}</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal Thêm ca làm việc */}
      {showScheduleModal && (
        <div className="modal-overlay" onClick={() => setShowScheduleModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Thêm ca làm việc</h3>
              <button className="modal-close-btn" onClick={() => setShowScheduleModal(false)}>&times;</button>
            </div>
            <form onSubmit={handleSubmitSchedule}>
              <div className="modal-body">
                <div className="form-group">
                  <label>Bác sĩ *</label>
                  <select
                    className="form-control"
                    value={scheduleForm.doctor_id}
                    onChange={(e) => setScheduleForm({ ...scheduleForm, doctor_id: e.target.value })}
                    required
                  >
                    {doctors.map((d) => (
                      <option key={d.id} value={d.id}>{d.name}</option>
                    ))}
                  </select>
                </div>
                <div className="form-group">
                  <label>Chi nhánh *</label>
                  <select
                    className="form-control"
                    value={scheduleForm.branch_id}
                    onChange={(e) => setScheduleForm({ ...scheduleForm, branch_id: e.target.value })}
                    required
                  >
                    {branches.map((b) => (
                      <option key={b.id} value={b.id}>{b.name}</option>
                    ))}
                  </select>
                </div>
                <div className="form-group">
                  <label>Ngày trong tuần *</label>
                  <select
                    className="form-control"
                    value={scheduleForm.day_of_week}
                    onChange={(e) => setScheduleForm({ ...scheduleForm, day_of_week: e.target.value })}
                    required
                  >
                    {DAY_NAMES.map((name, index) => (
                      <option key={index} value={index}>{name}</option>
                    ))}
                  </select>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                  <div className="form-group" style={{ marginBottom: 0 }}>
                    <label>Giờ bắt đầu *</label>
                    <input
                      className="form-control"
                      type="time"
                      value={scheduleForm.start_time}
                      onChange={(e) => setScheduleForm({ ...scheduleForm, start_time: e.target.value })}
                      required
                    />
                  </div>
                  <div className="form-group" style={{ marginBottom: 0 }}>
                    <label>Giờ kết thúc *</label>
                    <input
                      className="form-control"
                      type="time"
                      value={scheduleForm.end_time}
                      onChange={(e) => setScheduleForm({ ...scheduleForm, end_time: e.target.value })}
                      required
                    />
                  </div>
                </div>
              </div>
              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick={() => setShowScheduleModal(false)}>Hủy</button>
                <button type="submit" className="btn btn-primary">Thêm ca làm việc</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
