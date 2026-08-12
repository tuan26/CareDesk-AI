import { useEffect, useState } from 'react';
import { API_BASE, getAuthHeaders } from '../api';

/**
 * Who is here right now.
 *
 * This is the screen a receptionist opens every morning, and that matters more
 * than its feature list: the clearest signal a pilot is working is whether
 * staff open the product without being told. Nothing else in CareDesk earns a
 * daily open the way this does.
 *
 * It is also where the visit record gets written — the doctor finishes, taps
 * "Ghi hồ sơ", and the same action closes the visit, books the revenue and
 * starts the follow-up chain.
 */

const STATE_LABEL = {
  waiting: { text: 'Chưa đến', bg: '#f1f5f9', fg: '#475569' },
  arrived: { text: 'Đã đến — đang chờ', bg: '#fef3c7', fg: '#92400e' },
  in_progress: { text: 'Đang khám', bg: '#dbeafe', fg: '#1e40af' },
  done: { text: 'Xong', bg: '#d1fae5', fg: '#065f46' },
  no_show: { text: 'Không đến', bg: '#fee2e2', fg: '#991b1b' },
  cancelled: { text: 'Đã hủy', bg: '#f1f5f9', fg: '#94a3b8' },
};

const EMPTY_RECORD = {
  chief_complaint: '', findings: '', treatment_done: '', advice: '', next_visit_days: '',
};

export default function QueuePage() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [openFor, setOpenFor] = useState(null);   // appointment id
  const [record, setRecord] = useState(EMPTY_RECORD);
  const [photos, setPhotos] = useState([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const load = async () => {
    try {
      const res = await fetch(`${API_BASE}/visits/queue`, { headers: getAuthHeaders() });
      if (res.ok) setRows(await res.json());
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // The waiting-time column is only useful if it moves.
    const timer = setInterval(load, 60000);
    return () => clearInterval(timer);
  }, []);

  const act = async (id, what) => {
    await fetch(`${API_BASE}/visits/queue/${id}/${what}`, {
      method: 'POST', headers: getAuthHeaders(),
    });
    load();
  };

  const openRecord = async (id) => {
    setOpenFor(id);
    setError('');
    setRecord(EMPTY_RECORD);
    setPhotos([]);
    const res = await fetch(`${API_BASE}/visits/records/${id}`, { headers: getAuthHeaders() });
    if (res.ok) {
      const data = await res.json();
      if (data) {
        setRecord({
          chief_complaint: data.chief_complaint || '',
          findings: data.findings || '',
          treatment_done: data.treatment_done || '',
          advice: data.advice || '',
          next_visit_days: data.next_visit_days ?? '',
        });
        setPhotos(data.photos || []);
      }
    }
  };

  const saveRecord = async () => {
    setSaving(true);
    setError('');
    const body = { ...record };
    body.next_visit_days = record.next_visit_days === '' ? null : Number(record.next_visit_days);
    const res = await fetch(`${API_BASE}/visits/records/${openFor}`, {
      method: 'PUT', headers: getAuthHeaders(), body: JSON.stringify(body),
    });
    setSaving(false);
    if (!res.ok) {
      setError('Không lưu được hồ sơ.');
      return;
    }
    setOpenFor(null);
    load();
  };

  const uploadPhoto = async (kind, file) => {
    if (!file) return;
    setError('');
    const form = new FormData();
    form.append('file', file);
    // Not getAuthHeaders(): that sets Content-Type: application/json, which
    // stops the browser adding the multipart boundary and the upload fails.
    const token = localStorage.getItem('caredesk_token');
    const res = await fetch(`${API_BASE}/visits/records/${openFor}/photos?kind=${kind}`, {
      method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: form,
    });
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      setError(d.detail || 'Không tải được ảnh lên.');
      return;
    }
    setPhotos([...photos, await res.json()]);
  };

  const removePhoto = async (id) => {
    if (!window.confirm('Xoá ảnh này?')) return;
    await fetch(`${API_BASE}/visits/photos/${id}`, { method: 'DELETE', headers: getAuthHeaders() });
    setPhotos(photos.filter((p) => p.id !== id));
  };

  if (loading) return <div style={{ padding: 24, textAlign: 'center' }}>Đang tải…</div>;

  const waitingCount = rows.filter((r) => r.queue_state === 'arrived').length;

  return (
    <div>
      <div className="page-header">
        <div className="page-title">
          <h1>Hàng đợi khám hôm nay</h1>
          <p>
            {rows.length} lịch hẹn
            {waitingCount > 0 && <> — <b style={{ color: '#92400e' }}>{waitingCount} khách đang chờ</b></>}
          </p>
        </div>
        <button className="btn btn-secondary" onClick={load}>Làm mới</button>
      </div>

      <div className="card-table-wrapper">
        {rows.length === 0 ? (
          <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
            Hôm nay chưa có lịch hẹn nào.
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Giờ</th><th>Khách hàng</th><th>Dịch vụ</th><th>Bác sĩ</th>
                <th>Trạng thái</th><th style={{ textAlign: 'right' }}>Thao tác</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const s = STATE_LABEL[r.queue_state] || STATE_LABEL.waiting;
                return (
                  <tr key={r.appointment_id}>
                    <td><b>{new Date(r.start_time).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })}</b></td>
                    <td>
                      {r.patient_name}
                      {r.patient_phone && <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{r.patient_phone}</div>}
                    </td>
                    <td>{r.service_name || '—'}</td>
                    <td>{r.doctor_name || '—'}</td>
                    <td>
                      <span style={{ background: s.bg, color: s.fg, padding: '3px 9px', borderRadius: 999, fontSize: 12, fontWeight: 600 }}>
                        {s.text}
                      </span>
                      {r.waited_minutes != null && (
                        <div style={{ fontSize: 12, color: r.waited_minutes > 20 ? '#b91c1c' : 'var(--text-muted)', marginTop: 3 }}>
                          chờ {r.waited_minutes} phút
                        </div>
                      )}
                    </td>
                    <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                      {r.queue_state === 'waiting' && (
                        <button className="btn btn-secondary btn-sm" onClick={() => act(r.appointment_id, 'arrive')}>Khách đến</button>
                      )}
                      {r.queue_state === 'arrived' && (
                        <button className="btn btn-primary btn-sm" onClick={() => act(r.appointment_id, 'start')}>Bắt đầu khám</button>
                      )}
                      {(r.queue_state === 'in_progress' || r.queue_state === 'done') && (
                        <button className="btn btn-primary btn-sm" onClick={() => openRecord(r.appointment_id)}>
                          {r.has_record ? 'Xem hồ sơ' : 'Ghi hồ sơ'}
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {openFor && (
        <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && setOpenFor(null)}>
          <div className="modal" style={{ maxWidth: 640 }}>
            <div className="modal-header"><h2>Hồ sơ buổi khám</h2></div>
            <div className="modal-body">
              {[
                ['chief_complaint', 'Khách than phiền gì', 'vd. Mụn viêm 2 tháng, vùng má'],
                ['findings', 'Bác sĩ ghi nhận', 'vd. Mụn viêm mức độ vừa, da dầu'],
                ['treatment_done', 'Đã làm gì hôm nay', 'vd. Lấy nhân mụn + chiếu LED'],
                ['advice', 'Dặn dò về nhà', 'vd. Tránh nắng, rửa mặt 2 lần/ngày'],
              ].map(([key, label, ph]) => (
                <div className="form-group" key={key}>
                  <label>{label}</label>
                  <textarea className="form-control" rows="2" placeholder={ph}
                    value={record[key]}
                    onChange={(e) => setRecord({ ...record, [key]: e.target.value })} />
                </div>
              ))}

              <div className="form-group">
                <label>Hẹn tái khám sau (ngày)</label>
                <input className="form-control" type="number" min="0" max="1095"
                  style={{ maxWidth: 160 }} placeholder="vd. 21"
                  value={record.next_visit_days}
                  onChange={(e) => setRecord({ ...record, next_visit_days: e.target.value })} />
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
                  Hệ thống sẽ tự nhắc khách quay lại đúng mốc này.
                </div>
              </div>

              <div className="form-group">
                <label>Ảnh trước / sau</label>
                <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 10 }}>
                  {photos.map((p) => (
                    <div key={p.id} style={{ position: 'relative' }}>
                      <PhotoThumb url={p.url} kind={p.kind} />
                      <button onClick={() => removePhoto(p.id)} title="Xoá"
                        style={{ position: 'absolute', top: -6, right: -6, width: 22, height: 22, borderRadius: 11, border: 'none', background: '#dc2626', color: '#fff', cursor: 'pointer', fontSize: 13, lineHeight: '20px' }}>×</button>
                    </div>
                  ))}
                </div>
                <div style={{ display: 'flex', gap: 10 }}>
                  {['before', 'after'].map((kind) => (
                    <label key={kind} className="btn btn-secondary btn-sm" style={{ cursor: 'pointer' }}>
                      + Ảnh {kind === 'before' ? 'trước' : 'sau'}
                      <input type="file" accept="image/jpeg,image/png,image/webp" hidden
                        onChange={(e) => { uploadPhoto(kind, e.target.files[0]); e.target.value = ''; }} />
                    </label>
                  ))}
                </div>
              </div>

              {error && <div style={{ color: '#b91c1c', fontSize: 13 }}>{error}</div>}
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => setOpenFor(null)}>Đóng</button>
              <button className="btn btn-primary" onClick={saveRecord} disabled={saving}>
                {saving ? 'Đang lưu…' : 'Lưu & hoàn tất buổi khám'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Patient photos are served from an authenticated endpoint, so a plain <img src>
 * would 401 — the browser sends no Authorization header. Fetch as a blob and
 * render that instead.
 */
function PhotoThumb({ url, kind }) {
  const [src, setSrc] = useState(null);

  useEffect(() => {
    let objectUrl;
    const token = localStorage.getItem('caredesk_token');
    // `url` is a path under the API prefix; API_BASE already carries the host.
    const full = url.startsWith('http') ? url : API_BASE.replace(/\/api\/v1$/, '') + url;
    fetch(full, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => (r.ok ? r.blob() : null))
      .then((blob) => {
        if (!blob) return;
        objectUrl = URL.createObjectURL(blob);
        setSrc(objectUrl);
      })
      .catch(() => {});
    return () => objectUrl && URL.revokeObjectURL(objectUrl);
  }, [url]);

  return (
    <div style={{ width: 92, textAlign: 'center' }}>
      <div style={{ width: 92, height: 92, borderRadius: 8, overflow: 'hidden', background: '#f1f5f9', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        {src ? <img src={src} alt={kind} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
          : <span style={{ fontSize: 11, color: '#94a3b8' }}>…</span>}
      </div>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
        {kind === 'before' ? 'Trước' : 'Sau'}
      </div>
    </div>
  );
}
