import { useEffect, useState } from 'react';
import { API_BASE, getAuthHeaders } from '../api';

const STATUS = {
  requested: 'Mới gửi', contacted: 'Đã liên hệ', converted: 'Đã tạo lịch hẹn', cancelled: 'Đã hủy',
};

const emptyForm = { doctor_id: '', branch_id: '', date: '', slot: '', note: '' };

function toLocalDate(value) {
  return value ? value.slice(0, 10) : new Date().toISOString().slice(0, 10);
}

function buildDateTime(date, slot, duration) {
  const [hour, minute] = slot.split(':').map(Number);
  const start = new Date(`${date}T00:00:00`);
  start.setHours(hour, minute, 0, 0);
  const end = new Date(start.getTime() + duration * 60_000);
  const format = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}T${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:00`;
  return { start_time: format(start), end_time: format(end) };
}

export default function BookingRequestsPage() {
  const [requests, setRequests] = useState([]);
  const [services, setServices] = useState([]);
  const [doctors, setDoctors] = useState([]);
  const [branches, setBranches] = useState([]);
  const [filter, setFilter] = useState('requested');
  const [selected, setSelected] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [slots, setSlots] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const suffix = filter ? `?request_status=${filter}` : '';
      const [requestRes, serviceRes, doctorRes, branchRes] = await Promise.all([
        fetch(`${API_BASE}/booking-requests${suffix}`, { headers: getAuthHeaders() }),
        fetch(`${API_BASE}/clinic/services`, { headers: getAuthHeaders() }),
        fetch(`${API_BASE}/clinic/doctors`, { headers: getAuthHeaders() }),
        fetch(`${API_BASE}/clinic/branches`, { headers: getAuthHeaders() }),
      ]);
      if (!requestRes.ok) throw new Error('Không thể tải yêu cầu đặt lịch.');
      setRequests(await requestRes.json());
      setServices(serviceRes.ok ? await serviceRes.json() : []);
      setDoctors(doctorRes.ok ? await doctorRes.json() : []);
      setBranches(branchRes.ok ? await branchRes.json() : []);
    } catch (e) { setError(e.message); } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, [filter]);

  const changeStatus = async (request, status) => {
    setError('');
    const res = await fetch(`${API_BASE}/booking-requests/${request.id}`, {
      method: 'PATCH', headers: getAuthHeaders(), body: JSON.stringify({ status }),
    });
    if (!res.ok) setError((await res.json().catch(() => ({}))).detail || 'Không thể cập nhật yêu cầu.');
    else load();
  };

  const openConvert = (request) => {
    const service = services.find((item) => item.id === request.service_id);
    // preferred_at is a real timestamp. Splitting preferred_time on a space
    // guessed at a format that differed between the chat and the web form, so
    // the dialog opened on the wrong day for one of them.
    const when = request.preferred_at ? new Date(request.preferred_at) : null;
    setSelected(request);
    setSlots([]);
    setError('');
    setForm({
      // The location and doctor the patient was actually offered, not whichever
      // happens to be first in the list.
      doctor_id: (request.doctor_id || doctors.find((doctor) => doctor.is_active)?.id || '').toString(),
      branch_id: (request.branch_id || branches[0]?.id || '').toString(),
      date: when ? toLocalDate(when.toISOString().slice(0, 10)) : '',
      slot: when ? when.toTimeString().slice(0, 5) : '',
      note: request.note || '',
      duration: service?.duration_minutes || 30,
    });
  };

  useEffect(() => {
    if (!selected || !form.doctor_id || !form.date || !selected.service_id) return;
    (async () => {
      const params = new URLSearchParams({ doctor_id: form.doctor_id, target_date: form.date, service_id: selected.service_id });
      const res = await fetch(`${API_BASE}/appointments/available-slots?${params}`, { headers: getAuthHeaders() });
      const data = res.ok ? await res.json() : { slots: [] };
      setSlots(data.slots || []);
      if (!data.slots?.includes(form.slot)) setForm((current) => ({ ...current, slot: '' }));
    })();
  }, [selected, form.doctor_id, form.date]);

  const convert = async (event) => {
    event.preventDefault();
    if (!form.slot) return;
    setSaving(true); setError('');
    const timing = buildDateTime(form.date, form.slot, form.duration);
    const res = await fetch(`${API_BASE}/booking-requests/${selected.id}/convert`, {
      method: 'POST', headers: getAuthHeaders(),
      body: JSON.stringify({ patient_id: selected.patient_id, service_id: selected.service_id,
        doctor_id: Number(form.doctor_id), branch_id: Number(form.branch_id), ...timing,
        status: 'pending', note: form.note || null }),
    });
    if (!res.ok) { setError((await res.json().catch(() => ({}))).detail || 'Không thể tạo lịch hẹn.'); setSaving(false); return; }
    setSelected(null); setSaving(false); load();
  };

  return <div>
    <div className="page-header"><div className="page-title"><h1>Yêu cầu đặt lịch</h1><p>AI chỉ ghi nhận yêu cầu. Lễ tân kiểm tra và tạo lịch hẹn chính thức tại đây.</p></div></div>
    {error && <div style={{ color: 'var(--danger-color)', marginBottom: 12 }}>{error}</div>}
    <div className="card-table-wrapper">
      <div className="card-header" style={{ gap: 12 }}><h2>Hộp yêu cầu ({requests.length})</h2>
        <select className="form-control" style={{ width: 180 }} value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="">Tất cả trạng thái</option>{Object.entries(STATUS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </div>
      {loading ? <div style={{ padding: 28, textAlign: 'center' }}>Đang tải...</div> : requests.length === 0 ? <div style={{ padding: 28, textAlign: 'center' }}>Không có yêu cầu phù hợp.</div> :
        <table className="custom-table"><thead><tr><th>Khách hàng</th><th>Nhu cầu / dịch vụ</th><th>Cơ sở / bác sĩ</th><th>Thời gian mong muốn</th><th>Ngôn ngữ</th><th>Trạng thái</th><th>Thao tác</th></tr></thead><tbody>
          {requests.map((request) => <tr key={request.id}><td><b>{request.full_name}</b><br /><small>{request.contact_value}</small></td><td>{request.service_or_need}<br /><small>{request.note}</small></td>
            {/* Reception assigns work by location. A request that names neither
                sends them back into the conversation to find out. */}
            <td>{request.branch_name || <span style={{ color: 'var(--text-muted, #94a3b8)' }}>Khách chưa chọn</span>}
              {request.doctor_name && <><br /><small>{request.doctor_name}</small></>}</td>
            <td>{request.preferred_time || 'Chưa chọn'}</td><td>{request.locale.toUpperCase()}</td><td><span className={`badge ${request.status === 'converted' ? 'completed' : request.status === 'cancelled' ? 'cancelled' : 'pending'}`}>{STATUS[request.status]}</span></td><td><div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {request.status === 'requested' && <button className="btn btn-secondary btn-sm" onClick={() => changeStatus(request, 'contacted')}>Đã liên hệ</button>}
            {['requested', 'contacted'].includes(request.status) && <button className="btn btn-primary btn-sm" onClick={() => openConvert(request)}>Tạo lịch hẹn</button>}
            {['requested', 'contacted'].includes(request.status) && <button className="btn btn-danger btn-sm" onClick={() => changeStatus(request, 'cancelled')}>Hủy</button>}
          </div></td></tr>)}
        </tbody></table>}
    </div>
    {selected && <div className="modal-overlay" onClick={() => setSelected(null)}><div className="modal-content" onClick={(e) => e.stopPropagation()}>
      <div className="modal-header"><h3>Xác nhận tạo lịch hẹn</h3><button className="modal-close-btn" onClick={() => setSelected(null)}>&times;</button></div>
      <form onSubmit={convert}><div className="modal-body"><p><b>{selected.full_name}</b> · {selected.service_or_need}</p><div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <div className="form-group"><label>Bác sĩ</label><select className="form-control" value={form.doctor_id} onChange={(e) => setForm({ ...form, doctor_id: e.target.value })} required>{doctors.filter((doctor) => doctor.is_active).map((doctor) => <option key={doctor.id} value={doctor.id}>{doctor.name}</option>)}</select></div>
        <div className="form-group"><label>Chi nhánh</label><select className="form-control" value={form.branch_id} onChange={(e) => setForm({ ...form, branch_id: e.target.value })} required>{branches.map((branch) => <option key={branch.id} value={branch.id}>{branch.name}</option>)}</select></div>
      </div><div className="form-group"><label>Ngày khám</label><input className="form-control" type="date" min={new Date().toISOString().slice(0, 10)} value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} required /></div>
      <div className="form-group"><label>Khung giờ trống</label><div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>{slots.map((slot) => <button key={slot} type="button" className={`btn btn-sm ${form.slot === slot ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setForm({ ...form, slot })}>{slot}</button>)}</div>{!slots.length && <small>Không có khung giờ trống cho lựa chọn này.</small>}</div>
      <div className="form-group"><label>Ghi chú</label><textarea className="form-control" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} /></div></div>
      <div className="modal-footer"><button type="button" className="btn btn-secondary" onClick={() => setSelected(null)}>Hủy</button><button className="btn btn-primary" disabled={!form.slot || saving}>{saving ? 'Đang tạo...' : 'Tạo lịch hẹn'}</button></div></form>
    </div></div>}
  </div>;
}
