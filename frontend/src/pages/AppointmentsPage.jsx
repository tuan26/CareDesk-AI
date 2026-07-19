import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { API_BASE } from '../api';

const STATUS_LABELS = {
  pending: 'Chờ xác nhận',
  awaiting_deposit: 'Chờ đặt cọc',
  confirmed: 'Đã xác nhận',
  completed: 'Hoàn thành',
  cancelled: 'Đã hủy',
  no_show: 'Vắng mặt'
};

const EMPTY_CREATE_FORM = {
  patient_mode: 'existing', // existing | new
  patient_id: '',
  new_patient: { full_name: '', phone: '', email: '' },
  service_id: '',
  doctor_id: '',
  branch_id: '',
  date: '',
  slot: '',
  note: ''
};

// Add minutes to "HH:MM" on a given "YYYY-MM-DD", return naive ISO "YYYY-MM-DDTHH:MM:00"
const buildDateTime = (dateStr, timeStr, addMinutes = 0) => {
  const [h, m] = timeStr.split(':').map(Number);
  const d = new Date(`${dateStr}T00:00:00`);
  d.setHours(h, m + addMinutes, 0, 0);
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:00`;
};

const toISODate = (d) => {
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};

// Monday of the week containing `d`
const getMonday = (d) => {
  const date = new Date(d);
  const day = (date.getDay() + 6) % 7; // 0 = Monday
  date.setDate(date.getDate() - day);
  date.setHours(0, 0, 0, 0);
  return date;
};

const DAY_NAMES_SHORT = ['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN'];
const CAL_START_HOUR = 8;
const CAL_END_HOUR = 21;
const HOUR_PX = 44;

const STATUS_COLORS = {
  pending: '#f59e0b', awaiting_deposit: '#f97316', confirmed: '#3b82f6', completed: '#10b981',
  cancelled: '#94a3b8', no_show: '#64748b'
};

function WeekCalendar({ appointments, weekStart, onSelect }) {
  const days = Array.from({ length: 7 }, (_, i) => {
    const d = new Date(weekStart);
    d.setDate(d.getDate() + i);
    return d;
  });
  const todayISO = toISODate(new Date());
  const gridHeight = (CAL_END_HOUR - CAL_START_HOUR) * HOUR_PX;

  const apptsForDay = (dayISO) =>
    appointments.filter(a => a.start_time.startsWith(dayISO) && a.status !== 'cancelled');

  return (
    <div style={{ display: 'flex', overflowX: 'auto' }}>
      {/* Hour gutter */}
      <div style={{ width: '48px', flexShrink: 0, paddingTop: '38px' }}>
        {Array.from({ length: CAL_END_HOUR - CAL_START_HOUR }, (_, i) => (
          <div key={i} style={{ height: `${HOUR_PX}px`, fontSize: '10px', color: 'var(--text-muted)', textAlign: 'right', paddingRight: '6px' }}>
            {CAL_START_HOUR + i}:00
          </div>
        ))}
      </div>
      {/* Day columns */}
      {days.map((day, di) => {
        const dayISO = toISODate(day);
        const isToday = dayISO === todayISO;
        return (
          <div key={di} style={{ flex: 1, minWidth: '120px', borderLeft: '1px solid var(--border-color)' }}>
            <div style={{
              height: '38px', textAlign: 'center', fontSize: '12px', fontWeight: 600, paddingTop: '4px',
              backgroundColor: isToday ? 'var(--primary-light)' : '#f8fafc',
              color: isToday ? 'var(--primary-color)' : 'var(--text-main)',
              borderBottom: '1px solid var(--border-color)'
            }}>
              {DAY_NAMES_SHORT[di]}<br />
              <span style={{ fontSize: '11px', fontWeight: isToday ? 700 : 400 }}>{day.getDate()}/{day.getMonth() + 1}</span>
            </div>
            <div style={{ position: 'relative', height: `${gridHeight}px` }}>
              {/* hour lines */}
              {Array.from({ length: CAL_END_HOUR - CAL_START_HOUR }, (_, i) => (
                <div key={i} style={{ position: 'absolute', top: `${i * HOUR_PX}px`, left: 0, right: 0, borderTop: '1px solid #f1f5f9' }} />
              ))}
              {/* appointment blocks */}
              {apptsForDay(dayISO).map((a) => {
                const start = new Date(a.start_time);
                const end = new Date(a.end_time);
                const top = ((start.getHours() + start.getMinutes() / 60) - CAL_START_HOUR) * HOUR_PX;
                const height = Math.max(((end - start) / 3600000) * HOUR_PX, 20);
                const color = STATUS_COLORS[a.status] || '#64748b';
                return (
                  <div
                    key={a.id}
                    onClick={() => onSelect(a)}
                    title={`${a.patient?.full_name} - ${a.service?.name}`}
                    style={{
                      position: 'absolute', top: `${top}px`, height: `${height}px`,
                      left: '3px', right: '3px', borderRadius: '6px', cursor: 'pointer',
                      backgroundColor: `${color}22`, borderLeft: `3px solid ${color}`,
                      padding: '2px 6px', overflow: 'hidden', fontSize: '10.5px', lineHeight: 1.3
                    }}
                  >
                    <div style={{ fontWeight: 700, color: 'var(--dark-color)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {start.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} {a.patient?.full_name}
                    </div>
                    <div style={{ color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {a.service?.name}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function AppointmentsPage() {
  const [appointments, setAppointments] = useState([]);
  const [doctors, setDoctors] = useState([]);
  const [services, setServices] = useState([]);
  const [branches, setBranches] = useState([]);
  const [patients, setPatients] = useState([]);
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  // Filters
  const [filterStatus, setFilterStatus] = useState('');
  const [filterDoctor, setFilterDoctor] = useState('');
  const [filterDate, setFilterDate] = useState('');

  // View mode: list | week (calendar)
  const [viewMode, setViewMode] = useState('list');
  const [weekStart, setWeekStart] = useState(getMonday(new Date()));
  const [selectedAppt, setSelectedAppt] = useState(null);
  const [reschedule, setReschedule] = useState(null); // { date, slot, slots, loading }

  // Create modal
  const [showModal, setShowModal] = useState(false);
  const [form, setForm] = useState(EMPTY_CREATE_FORM);
  const [availableSlots, setAvailableSlots] = useState([]);
  const [slotsLoading, setSlotsLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const navigate = useNavigate();

  const getHeaders = () => {
    const token = localStorage.getItem('caredesk_token');
    return {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    };
  };

  const isManager = user && (user.role === 'owner' || user.role === 'admin');

  const fetchAppointments = async () => {
    try {
      const headers = getHeaders();
      const params = new URLSearchParams();
      if (filterStatus) params.append('status', filterStatus);
      if (filterDoctor) params.append('doctor_id', filterDoctor);
      if (viewMode === 'week') {
        const weekEnd = new Date(weekStart);
        weekEnd.setDate(weekEnd.getDate() + 6);
        params.append('start_date', toISODate(weekStart));
        params.append('end_date', toISODate(weekEnd));
      } else if (filterDate) {
        params.append('start_date', filterDate);
        params.append('end_date', filterDate);
      }
      const qs = params.toString();
      const response = await fetch(`${API_BASE}/appointments${qs ? '?' + qs : ''}`, { headers });
      if (response.status === 401) throw new Error('Unauthorized');
      setAppointments(await response.json());
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

  const fetchReferenceData = async () => {
    try {
      const headers = getHeaders();
      const [meRes, doctorsRes, servicesRes, branchesRes, patientsRes] = await Promise.all([
        fetch(`${API_BASE}/auth/me`, { headers }),
        fetch(`${API_BASE}/clinic/doctors`, { headers }),
        fetch(`${API_BASE}/clinic/services`, { headers }),
        fetch(`${API_BASE}/clinic/branches`, { headers }),
        fetch(`${API_BASE}/appointments/patients`, { headers })
      ]);
      if (meRes.status === 401) throw new Error('Unauthorized');
      setUser(await meRes.json());
      setDoctors(await doctorsRes.json());
      setServices(await servicesRes.json());
      setBranches(await branchesRes.json());
      setPatients(await patientsRes.json());
    } catch (err) {
      console.error(err);
      if (err.message === 'Unauthorized') {
        localStorage.removeItem('caredesk_token');
        navigate('/login');
      }
    }
  };

  useEffect(() => {
    fetchReferenceData();
  }, [navigate]);

  useEffect(() => {
    fetchAppointments();
  }, [filterStatus, filterDoctor, filterDate, viewMode, weekStart]);

  // Fetch available slots when doctor + date + service selected in create modal
  useEffect(() => {
    const { doctor_id, date, service_id } = form;
    if (!showModal || !doctor_id || !date || !service_id) {
      setAvailableSlots([]);
      return;
    }
    const fetchSlots = async () => {
      setSlotsLoading(true);
      try {
        const params = new URLSearchParams({ doctor_id, target_date: date, service_id });
        const response = await fetch(`${API_BASE}/appointments/available-slots?${params}`, { headers: getHeaders() });
        if (response.ok) {
          const data = await response.json();
          setAvailableSlots(data.slots || []);
        } else {
          setAvailableSlots([]);
        }
      } catch (err) {
        console.error(err);
        setAvailableSlots([]);
      } finally {
        setSlotsLoading(false);
      }
    };
    fetchSlots();
  }, [showModal, form.doctor_id, form.date, form.service_id]);

  const openCreateModal = () => {
    setForm({
      ...EMPTY_CREATE_FORM,
      patient_mode: patients.length > 0 ? 'existing' : 'new',
      patient_id: patients[0]?.id || '',
      service_id: services[0]?.id || '',
      doctor_id: doctors.find(d => d.is_active)?.id || doctors[0]?.id || '',
      branch_id: branches[0]?.id || '',
      date: new Date().toISOString().split('T')[0]
    });
    setAvailableSlots([]);
    setShowModal(true);
  };

  const handleCreateAppointment = async (e) => {
    e.preventDefault();
    if (!form.slot) {
      alert('Vui lòng chọn một khung giờ trống.');
      return;
    }
    setSubmitting(true);
    try {
      // 1. Resolve patient (create new lead if needed)
      let patientId = form.patient_id;
      if (form.patient_mode === 'new') {
        const patientRes = await fetch(`${API_BASE}/appointments/patients`, {
          method: 'POST',
          headers: getHeaders(),
          body: JSON.stringify({
            full_name: form.new_patient.full_name,
            phone: form.new_patient.phone || null,
            email: form.new_patient.email || null,
            source: 'web',
            consent_given: true
          })
        });
        if (!patientRes.ok) {
          const data = await patientRes.json().catch(() => null);
          throw new Error(data?.detail || 'Không thể tạo hồ sơ khách hàng.');
        }
        patientId = (await patientRes.json()).id;
      }

      // 2. Create appointment
      const service = services.find(s => s.id === parseInt(form.service_id, 10));
      const payload = {
        patient_id: parseInt(patientId, 10),
        service_id: parseInt(form.service_id, 10),
        doctor_id: parseInt(form.doctor_id, 10),
        branch_id: parseInt(form.branch_id, 10),
        start_time: buildDateTime(form.date, form.slot),
        end_time: buildDateTime(form.date, form.slot, service?.duration_minutes || 30),
        status: 'pending',
        note: form.note || null
      };
      const response = await fetch(`${API_BASE}/appointments`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify(payload)
      });
      if (!response.ok) {
        const data = await response.json().catch(() => null);
        throw new Error(data?.detail || 'Không thể tạo lịch hẹn.');
      }
      setShowModal(false);
      fetchAppointments();
      fetchReferenceData();
    } catch (err) {
      console.error(err);
      alert(err.message || 'Lỗi kết nối máy chủ.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleUpdateStatus = async (appt, newStatus) => {
    const label = STATUS_LABELS[newStatus] || newStatus;
    if (!window.confirm(`Chuyển lịch hẹn của "${appt.patient?.full_name}" sang trạng thái "${label}"?`)) return;
    try {
      const payload = {
        patient_id: appt.patient_id,
        service_id: appt.service_id,
        doctor_id: appt.doctor_id,
        branch_id: appt.branch_id,
        start_time: appt.start_time,
        end_time: appt.end_time,
        status: newStatus,
        note: appt.note
      };
      const response = await fetch(`${API_BASE}/appointments/${appt.id}`, {
        method: 'PUT',
        headers: getHeaders(),
        body: JSON.stringify(payload)
      });
      if (response.ok) {
        fetchAppointments();
      } else {
        const data = await response.json().catch(() => null);
        alert(data?.detail || 'Không thể cập nhật trạng thái.');
      }
    } catch (err) {
      console.error(err);
      alert('Lỗi kết nối máy chủ.');
    }
  };

  // --- Reschedule (from calendar detail modal) ---
  const openReschedule = (appt) => {
    setReschedule({ appt, date: appt.start_time.split('T')[0], slot: '', slots: [], loading: false });
  };

  useEffect(() => {
    if (!reschedule?.appt || !reschedule.date) return;
    const load = async () => {
      setReschedule(r => ({ ...r, loading: true }));
      try {
        const params = new URLSearchParams({
          doctor_id: reschedule.appt.doctor_id,
          target_date: reschedule.date,
          service_id: reschedule.appt.service_id
        });
        const res = await fetch(`${API_BASE}/appointments/available-slots?${params}`, { headers: getHeaders() });
        const data = res.ok ? await res.json() : { slots: [] };
        setReschedule(r => r ? { ...r, slots: data.slots || [], loading: false } : r);
      } catch {
        setReschedule(r => r ? { ...r, slots: [], loading: false } : r);
      }
    };
    load();
  }, [reschedule?.date]);

  const handleReschedule = async () => {
    const { appt, date, slot } = reschedule;
    if (!slot) return;
    const service = services.find(s => s.id === appt.service_id);
    const duration = service?.duration_minutes || 30;
    try {
      const payload = {
        patient_id: appt.patient_id,
        service_id: appt.service_id,
        doctor_id: appt.doctor_id,
        branch_id: appt.branch_id,
        start_time: buildDateTime(date, slot),
        end_time: buildDateTime(date, slot, duration),
        status: appt.status,
        note: appt.note
      };
      const res = await fetch(`${API_BASE}/appointments/${appt.id}`, {
        method: 'PUT',
        headers: getHeaders(),
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        setReschedule(null);
        setSelectedAppt(null);
        fetchAppointments();
      } else {
        const data = await res.json().catch(() => null);
        alert(data?.detail || 'Không thể đổi lịch.');
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleSendReminder = async (appt) => {
    try {
      const response = await fetch(`${API_BASE}/appointments/${appt.id}/remind`, {
        method: 'POST',
        headers: getHeaders()
      });
      const data = await response.json().catch(() => null);
      if (response.ok) {
        alert(data?.message || 'Đã gửi email nhắc lịch.');
      } else {
        alert(data?.detail || 'Không thể gửi nhắc lịch.');
      }
    } catch (err) {
      console.error(err);
      alert('Lỗi kết nối máy chủ.');
    }
  };

  const handleDelete = async (appt) => {
    if (!window.confirm(`Xóa vĩnh viễn lịch hẹn của "${appt.patient?.full_name}"?`)) return;
    try {
      const response = await fetch(`${API_BASE}/appointments/${appt.id}`, {
        method: 'DELETE',
        headers: getHeaders()
      });
      if (response.ok || response.status === 204) {
        fetchAppointments();
      } else {
        const data = await response.json().catch(() => null);
        alert(data?.detail || 'Không thể xóa lịch hẹn.');
      }
    } catch (err) {
      console.error(err);
      alert('Lỗi kết nối máy chủ.');
    }
  };

  const formatDateTime = (iso) => {
    const d = new Date(iso);
    return `${d.toLocaleDateString('vi-VN')} ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
  };

  if (loading) return <div style={{ padding: '24px', textAlign: 'center' }}>Đang tải danh sách lịch hẹn...</div>;

  return (
    <div>
      <div className="page-header">
        <div className="page-title">
          <h1>Quản lý lịch hẹn</h1>
          <p>Theo dõi, xác nhận và nhắc lịch hẹn khám của khách hàng.</p>
        </div>
        <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
          <div style={{ display: 'flex', border: '1px solid var(--border-color)', borderRadius: '8px', overflow: 'hidden' }}>
            <button
              className="btn btn-sm"
              style={{ borderRadius: 0, background: viewMode === 'list' ? 'var(--primary-color)' : 'white', color: viewMode === 'list' ? 'white' : 'var(--text-main)' }}
              onClick={() => setViewMode('list')}
            >
              ☰ Danh sách
            </button>
            <button
              className="btn btn-sm"
              style={{ borderRadius: 0, background: viewMode === 'week' ? 'var(--primary-color)' : 'white', color: viewMode === 'week' ? 'white' : 'var(--text-main)' }}
              onClick={() => setViewMode('week')}
            >
              📅 Lịch tuần
            </button>
          </div>
          <button className="btn btn-primary" onClick={openCreateModal}>+ Tạo lịch hẹn</button>
        </div>
      </div>

      {/* Bộ lọc */}
      <div className="card-table-wrapper" style={{ marginBottom: '24px' }}>
        <div style={{ padding: '16px 24px', display: 'flex', gap: '16px', alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div className="form-group" style={{ marginBottom: 0, minWidth: '180px' }}>
            <label>Trạng thái</label>
            <select className="form-control" value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
              <option value="">Tất cả trạng thái</option>
              {Object.entries(STATUS_LABELS).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </div>
          <div className="form-group" style={{ marginBottom: 0, minWidth: '220px' }}>
            <label>Bác sĩ</label>
            <select className="form-control" value={filterDoctor} onChange={(e) => setFilterDoctor(e.target.value)}>
              <option value="">Tất cả bác sĩ</option>
              {doctors.map((d) => (
                <option key={d.id} value={d.id}>{d.name}</option>
              ))}
            </select>
          </div>
          {viewMode === 'list' ? (
            <div className="form-group" style={{ marginBottom: 0, minWidth: '180px' }}>
              <label>Ngày khám</label>
              <input className="form-control" type="date" value={filterDate} onChange={(e) => setFilterDate(e.target.value)} />
            </div>
          ) : (
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              <button className="btn btn-secondary btn-sm" onClick={() => { const d = new Date(weekStart); d.setDate(d.getDate() - 7); setWeekStart(d); }}>‹ Tuần trước</button>
              <button className="btn btn-secondary btn-sm" onClick={() => setWeekStart(getMonday(new Date()))}>Tuần này</button>
              <button className="btn btn-secondary btn-sm" onClick={() => { const d = new Date(weekStart); d.setDate(d.getDate() + 7); setWeekStart(d); }}>Tuần sau ›</button>
              <span style={{ fontSize: '13px', fontWeight: 600, marginLeft: '8px' }}>
                {weekStart.toLocaleDateString('vi-VN')} — {new Date(weekStart.getTime() + 6 * 86400000).toLocaleDateString('vi-VN')}
              </span>
            </div>
          )}
          {(filterStatus || filterDoctor || filterDate) && (
            <button
              className="btn btn-secondary"
              onClick={() => { setFilterStatus(''); setFilterDoctor(''); setFilterDate(''); }}
            >
              Xóa bộ lọc
            </button>
          )}
        </div>
      </div>

      {/* Lịch tuần */}
      {viewMode === 'week' && (
        <div className="card-table-wrapper">
          <div className="card-header">
            <h2>Lịch tuần ({appointments.filter(a => a.status !== 'cancelled').length} ca)</h2>
            <div style={{ display: 'flex', gap: '12px', fontSize: '11px', alignItems: 'center' }}>
              {Object.entries(STATUS_LABELS).filter(([k]) => k !== 'cancelled').map(([k, label]) => (
                <span key={k} style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <span style={{ width: '10px', height: '10px', borderRadius: '2px', background: STATUS_COLORS[k], display: 'inline-block' }} />
                  {label}
                </span>
              ))}
            </div>
          </div>
          <WeekCalendar appointments={appointments} weekStart={weekStart} onSelect={setSelectedAppt} />
        </div>
      )}

      {/* Bảng lịch hẹn */}
      {viewMode === 'list' && (
      <div className="card-table-wrapper">
        <div className="card-header">
          <h2>Danh sách lịch hẹn ({appointments.length})</h2>
        </div>
        {appointments.length === 0 ? (
          <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)' }}>
            Không có lịch hẹn nào khớp với bộ lọc hiện tại.
          </div>
        ) : (
          <table className="custom-table">
            <thead>
              <tr>
                <th>Khách hàng</th>
                <th>Dịch vụ</th>
                <th>Bác sĩ / Chi nhánh</th>
                <th>Thời gian khám</th>
                <th>Trạng thái</th>
                <th style={{ width: '260px' }}>Thao tác</th>
              </tr>
            </thead>
            <tbody>
              {appointments.map((appt) => (
                <tr key={appt.id}>
                  <td>
                    <div style={{ fontWeight: 600 }}>{appt.patient?.full_name}</div>
                    <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{appt.patient?.phone}</div>
                  </td>
                  <td>{appt.service?.name}</td>
                  <td>
                    <div>{appt.doctor?.name}</div>
                    <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{appt.branch?.name}</div>
                  </td>
                  <td style={{ whiteSpace: 'nowrap' }}>{formatDateTime(appt.start_time)}</td>
                  <td>
                    <span className={`badge ${appt.status}`}>{STATUS_LABELS[appt.status] || appt.status}</span>
                  </td>
                  <td>
                    <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                      {appt.status === 'pending' && (
                        <button className="btn btn-primary btn-sm" onClick={() => handleUpdateStatus(appt, 'confirmed')}>Xác nhận</button>
                      )}
                      {appt.status === 'confirmed' && (
                        <>
                          <button className="btn btn-primary btn-sm" onClick={() => handleUpdateStatus(appt, 'completed')}>Hoàn thành</button>
                          <button className="btn btn-secondary btn-sm" onClick={() => handleUpdateStatus(appt, 'no_show')}>Vắng mặt</button>
                        </>
                      )}
                      {(appt.status === 'pending' || appt.status === 'confirmed') && (
                        <>
                          {appt.patient?.email && (
                            <button className="btn btn-secondary btn-sm" onClick={() => handleSendReminder(appt)}>Nhắc lịch</button>
                          )}
                          <button className="btn btn-secondary btn-sm" style={{ color: 'var(--danger-color)' }} onClick={() => handleUpdateStatus(appt, 'cancelled')}>Hủy hẹn</button>
                        </>
                      )}
                      {isManager && (
                        <button className="btn btn-danger btn-sm" onClick={() => handleDelete(appt)}>Xóa</button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      )}

      {/* Modal chi tiết lịch hẹn (từ calendar) */}
      {selectedAppt && (
        <div className="modal-overlay" onClick={() => { setSelectedAppt(null); setReschedule(null); }}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Lịch hẹn #{selectedAppt.id}</h3>
              <button className="modal-close-btn" onClick={() => { setSelectedAppt(null); setReschedule(null); }}>&times;</button>
            </div>
            <div className="modal-body">
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', fontSize: '14px' }}>
                <div><b>Khách hàng:</b> {selectedAppt.patient?.full_name} ({selectedAppt.patient?.phone || '—'})</div>
                <div><b>Dịch vụ:</b> {selectedAppt.service?.name}</div>
                <div><b>Bác sĩ:</b> {selectedAppt.doctor?.name} · <b>Chi nhánh:</b> {selectedAppt.branch?.name}</div>
                <div><b>Thời gian:</b> {formatDateTime(selectedAppt.start_time)}</div>
                <div><b>Trạng thái:</b> <span className={`badge ${selectedAppt.status}`}>{STATUS_LABELS[selectedAppt.status]}</span></div>
                {selectedAppt.note && <div><b>Ghi chú:</b> {selectedAppt.note}</div>}
              </div>

              {/* Reschedule section */}
              {reschedule ? (
                <div style={{ marginTop: '16px', borderTop: '1px solid var(--border-color)', paddingTop: '16px' }}>
                  <div className="form-group">
                    <label>Đổi sang ngày</label>
                    <input className="form-control" type="date" value={reschedule.date}
                      min={new Date().toISOString().split('T')[0]}
                      onChange={(e) => setReschedule({ ...reschedule, date: e.target.value, slot: '' })} />
                  </div>
                  <div className="form-group" style={{ marginBottom: 0 }}>
                    <label>Khung giờ trống</label>
                    {reschedule.loading ? (
                      <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>Đang tra cứu...</div>
                    ) : reschedule.slots.length === 0 ? (
                      <div style={{ fontSize: '13px', color: 'var(--warning-color)' }}>Không có khung giờ trống ngày này.</div>
                    ) : (
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                        {reschedule.slots.map((s) => (
                          <button key={s} type="button"
                            className={`btn btn-sm ${reschedule.slot === s ? 'btn-primary' : 'btn-secondary'}`}
                            onClick={() => setReschedule({ ...reschedule, slot: s })}>
                            {s}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ) : null}
            </div>
            <div className="modal-footer" style={{ flexWrap: 'wrap' }}>
              {reschedule ? (
                <>
                  <button className="btn btn-secondary" onClick={() => setReschedule(null)}>Quay lại</button>
                  <button className="btn btn-primary" disabled={!reschedule.slot} onClick={handleReschedule}>Xác nhận đổi lịch</button>
                </>
              ) : (
                <>
                  {selectedAppt.status === 'pending' && (
                    <button className="btn btn-primary btn-sm" onClick={() => { handleUpdateStatus(selectedAppt, 'confirmed'); setSelectedAppt(null); }}>Xác nhận</button>
                  )}
                  {selectedAppt.status === 'confirmed' && (
                    <button className="btn btn-primary btn-sm" onClick={() => { handleUpdateStatus(selectedAppt, 'completed'); setSelectedAppt(null); }}>Hoàn thành</button>
                  )}
                  {(selectedAppt.status === 'pending' || selectedAppt.status === 'confirmed') && (
                    <>
                      <button className="btn btn-secondary btn-sm" onClick={() => openReschedule(selectedAppt)}>🗓️ Đổi lịch</button>
                      <button className="btn btn-secondary btn-sm" style={{ color: 'var(--danger-color)' }}
                        onClick={() => { handleUpdateStatus(selectedAppt, 'cancelled'); setSelectedAppt(null); }}>Hủy hẹn</button>
                    </>
                  )}
                  <button className="btn btn-secondary btn-sm" onClick={() => setSelectedAppt(null)}>Đóng</button>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Modal Tạo lịch hẹn */}
      {showModal && (
        <div className="modal-overlay" onClick={() => setShowModal(false)}>
          <div className="modal-content" style={{ width: '640px' }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Tạo lịch hẹn mới</h3>
              <button className="modal-close-btn" onClick={() => setShowModal(false)}>&times;</button>
            </div>
            <form onSubmit={handleCreateAppointment}>
              <div className="modal-body">
                {/* Khách hàng */}
                <div className="form-group">
                  <label>Khách hàng *</label>
                  <div style={{ display: 'flex', gap: '16px', marginBottom: '10px' }}>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', textTransform: 'none', fontSize: '13px', marginBottom: 0 }}>
                      <input
                        type="radio"
                        checked={form.patient_mode === 'existing'}
                        onChange={() => setForm({ ...form, patient_mode: 'existing' })}
                        disabled={patients.length === 0}
                      />
                      Khách đã có hồ sơ
                    </label>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', textTransform: 'none', fontSize: '13px', marginBottom: 0 }}>
                      <input
                        type="radio"
                        checked={form.patient_mode === 'new'}
                        onChange={() => setForm({ ...form, patient_mode: 'new' })}
                      />
                      Khách mới
                    </label>
                  </div>
                  {form.patient_mode === 'existing' ? (
                    <select
                      className="form-control"
                      value={form.patient_id}
                      onChange={(e) => setForm({ ...form, patient_id: e.target.value })}
                      required
                    >
                      {patients.map((p) => (
                        <option key={p.id} value={p.id}>{p.full_name} {p.phone ? `(${p.phone})` : ''}</option>
                      ))}
                    </select>
                  ) : (
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '10px' }}>
                      <input
                        className="form-control"
                        value={form.new_patient.full_name}
                        onChange={(e) => setForm({ ...form, new_patient: { ...form.new_patient, full_name: e.target.value } })}
                        placeholder="Họ và tên *"
                        required
                      />
                      <input
                        className="form-control"
                        value={form.new_patient.phone}
                        onChange={(e) => setForm({ ...form, new_patient: { ...form.new_patient, phone: e.target.value } })}
                        placeholder="Số điện thoại"
                      />
                      <input
                        className="form-control"
                        type="email"
                        value={form.new_patient.email}
                        onChange={(e) => setForm({ ...form, new_patient: { ...form.new_patient, email: e.target.value } })}
                        placeholder="Email (nhận nhắc lịch)"
                      />
                    </div>
                  )}
                </div>

                {/* Dịch vụ & Bác sĩ */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                  <div className="form-group">
                    <label>Dịch vụ *</label>
                    <select
                      className="form-control"
                      value={form.service_id}
                      onChange={(e) => setForm({ ...form, service_id: e.target.value, slot: '' })}
                      required
                    >
                      {services.map((s) => (
                        <option key={s.id} value={s.id}>{s.name} ({s.duration_minutes}p)</option>
                      ))}
                    </select>
                  </div>
                  <div className="form-group">
                    <label>Bác sĩ *</label>
                    <select
                      className="form-control"
                      value={form.doctor_id}
                      onChange={(e) => setForm({ ...form, doctor_id: e.target.value, slot: '' })}
                      required
                    >
                      {doctors.filter(d => d.is_active).map((d) => (
                        <option key={d.id} value={d.id}>{d.name}</option>
                      ))}
                    </select>
                  </div>
                </div>

                {/* Chi nhánh & Ngày */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                  <div className="form-group">
                    <label>Chi nhánh *</label>
                    <select
                      className="form-control"
                      value={form.branch_id}
                      onChange={(e) => setForm({ ...form, branch_id: e.target.value })}
                      required
                    >
                      {branches.map((b) => (
                        <option key={b.id} value={b.id}>{b.name}</option>
                      ))}
                    </select>
                  </div>
                  <div className="form-group">
                    <label>Ngày khám *</label>
                    <input
                      className="form-control"
                      type="date"
                      value={form.date}
                      min={new Date().toISOString().split('T')[0]}
                      onChange={(e) => setForm({ ...form, date: e.target.value, slot: '' })}
                      required
                    />
                  </div>
                </div>

                {/* Khung giờ trống */}
                <div className="form-group">
                  <label>Khung giờ trống {form.slot && `— đã chọn ${form.slot}`}</label>
                  {slotsLoading ? (
                    <div style={{ fontSize: '13px', color: 'var(--text-muted)', padding: '8px 0' }}>Đang tra cứu khung giờ trống...</div>
                  ) : availableSlots.length === 0 ? (
                    <div style={{ fontSize: '13px', color: 'var(--warning-color)', padding: '8px 0' }}>
                      Bác sĩ không có khung giờ trống ngày này (chưa xếp ca làm việc hoặc đã kín lịch). Vui lòng chọn ngày/bác sĩ khác.
                    </div>
                  ) : (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                      {availableSlots.map((slot) => (
                        <button
                          key={slot}
                          type="button"
                          className={`btn btn-sm ${form.slot === slot ? 'btn-primary' : 'btn-secondary'}`}
                          onClick={() => setForm({ ...form, slot })}
                        >
                          {slot}
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                <div className="form-group" style={{ marginBottom: 0 }}>
                  <label>Ghi chú</label>
                  <textarea
                    className="form-control"
                    rows={2}
                    style={{ resize: 'vertical' }}
                    value={form.note}
                    onChange={(e) => setForm({ ...form, note: e.target.value })}
                    placeholder="Ghi chú thêm về tình trạng khách hàng..."
                  />
                </div>
              </div>
              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick={() => setShowModal(false)}>Hủy</button>
                <button type="submit" className="btn btn-primary" disabled={submitting || !form.slot}>
                  {submitting ? 'Đang tạo...' : 'Tạo lịch hẹn'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
