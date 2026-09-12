import { useState } from 'react';
import { API_BASE, getAuthHeaders } from '../api';

const money = (v) => `${Math.round(v || 0).toLocaleString('vi-VN')}₫`;

const authHeader = () => {
  // FormData sets its own multipart boundary; sending our JSON Content-Type
  // with it makes the request unparseable on the server.
  const { Authorization } = getAuthHeaders();
  return { Authorization };
};

export default function ImportPage() {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [mapping, setMapping] = useState({});
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const reset = () => { setPreview(null); setMapping({}); setResult(null); setError(''); };

  const choose = async (chosen) => {
    setFile(chosen); reset();
    if (!chosen) return;
    setBusy(true);
    const body = new FormData();
    body.append('file', chosen);
    const res = await fetch(`${API_BASE}/import/patients/preview`, {
      method: 'POST', headers: authHeader(), body,
    });
    if (!res.ok) {
      setError((await res.json().catch(() => ({}))).detail || 'Không đọc được file.');
      setBusy(false);
      return;
    }
    const data = await res.json();
    setPreview(data);
    setMapping(data.suggested_mapping || {});
    setBusy(false);
  };

  const run = async (dryRun) => {
    setBusy(true); setError('');
    const body = new FormData();
    body.append('file', file);
    body.append('mapping', JSON.stringify(mapping));
    body.append('dry_run', dryRun ? 'true' : 'false');
    const res = await fetch(`${API_BASE}/import/patients/run`, {
      method: 'POST', headers: authHeader(), body,
    });
    if (!res.ok) setError((await res.json().catch(() => ({}))).detail || 'Nhập dữ liệu thất bại.');
    else setResult(await res.json());
    setBusy(false);
  };

  const missing = (preview?.fields || [])
    .filter((f) => f.required && mapping[f.key] === undefined)
    .map((f) => f.label);

  return <div>
    <div className="page-header">
      <div className="page-title">
        <h1>Nhập khách hàng từ Excel</h1>
        <p>
          Cơ hội đáng thu hồi nào cũng nằm trong quá khứ. Chưa nhập file khách cũ thì
          hệ thống chỉ thấy khách đến từ hôm cài đặt trở đi.
        </p>
      </div>
    </div>

    {error && <div style={{ color: 'var(--danger-color)', marginBottom: 12 }}>{error}</div>}

    <div className="card" style={{ padding: 16, marginBottom: 18 }}>
      <label style={{ fontWeight: 600, display: 'block', marginBottom: 8 }}>
        Bước 1 — Chọn file (.xlsx hoặc .csv)
      </label>
      <input type="file" accept=".xlsx,.xlsm,.csv" className="form-control"
             onChange={(e) => choose(e.target.files?.[0] || null)} />
      <div style={{ fontSize: 12, color: 'var(--text-muted, #64748b)', marginTop: 8 }}>
        File Excel 2003 (.xls) chưa hỗ trợ — mở bằng Excel, chọn Save As → Excel Workbook (.xlsx).
      </div>
    </div>

    {busy && !preview && <div style={{ padding: 20, textAlign: 'center' }}>Đang đọc file...</div>}

    {preview && <>
      <div className="card-table-wrapper" style={{ marginBottom: 18 }}>
        <div className="card-header">
          <h2>Bước 2 — Xác nhận từng cột ({preview.row_count} dòng)</h2>
        </div>
        <div style={{ padding: '10px 16px', fontSize: 13, color: 'var(--text-muted, #64748b)' }}>
          {preview.note}
        </div>
        <table className="custom-table">
          <thead><tr><th style={{ width: 200 }}>Trường</th><th>Cột trong file</th><th>Dữ liệu mẫu</th></tr></thead>
          <tbody>
            {preview.fields.map((field) => {
              const column = mapping[field.key];
              const sample = preview.sample_rows
                .map((r) => r[column]).filter(Boolean).slice(0, 2).join(' · ');
              return <tr key={field.key}>
                <td>{field.label}{field.required && <span style={{ color: 'var(--danger-color)' }}> *</span>}</td>
                <td>
                  <select className="form-control" value={column === undefined ? '' : column}
                          onChange={(e) => {
                            const next = { ...mapping };
                            if (e.target.value === '') delete next[field.key];
                            else next[field.key] = Number(e.target.value);
                            setMapping(next);
                          }}>
                    <option value="">— không có —</option>
                    {preview.headers.map((h, i) => (
                      <option key={i} value={i}>{h || `Cột ${i + 1}`}</option>
                    ))}
                  </select>
                </td>
                {/* The clinic's own data next to the guess: far easier to check
                    than a field name on its own. */}
                <td style={{ fontSize: 12, color: 'var(--text-muted, #64748b)' }}>{sample || '—'}</td>
              </tr>;
            })}
          </tbody>
        </table>
      </div>

      {missing.length > 0 && <div style={{ color: 'var(--danger-color)', marginBottom: 12 }}>
        Còn thiếu cột bắt buộc: {missing.join(', ')}
      </div>}

      <div className="card" style={{ padding: 16, marginBottom: 18 }}>
        <label style={{ fontWeight: 600, display: 'block', marginBottom: 8 }}>
          Bước 3 — Thử trước, rồi mới nhập thật
        </label>
        <div style={{ fontSize: 13, color: 'var(--text-muted, #64748b)', marginBottom: 10 }}>
          Bản thử báo cáo y hệt lần chạy thật nhưng không ghi gì. Nhập xong thì không hoàn tác được.
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn btn-secondary" disabled={busy || missing.length > 0}
                  onClick={() => run(true)}>Chạy thử</button>
          <button className="btn btn-primary"
                  disabled={busy || missing.length > 0 || !result?.dry_run}
                  onClick={() => run(false)}>
            Nhập thật vào hệ thống
          </button>
        </div>
        {!result?.dry_run && <div style={{ fontSize: 12, color: 'var(--text-muted, #64748b)', marginTop: 8 }}>
          Chạy thử trước đã, rồi nút nhập thật mới bật.
        </div>}
      </div>
    </>}

    {result && <div className="card" style={{ padding: 16 }}>
      <h3 style={{ margin: '0 0 10px' }}>
        {result.dry_run ? 'Kết quả chạy thử (chưa ghi gì)' : '✓ Đã nhập vào hệ thống'}
      </h3>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12 }}>
        {[
          ['Đọc được', result.rows_read],
          ['Khách mới', result.patients_created],
          ['Khách cập nhật', result.patients_updated],
          ['Lượt khám cũ', result.visits_created],
          ['Bỏ qua', result.skipped],
        ].map(([label, value]) => <div key={label} style={{ textAlign: 'center', padding: '10px 6px', background: 'var(--bg-subtle, #f8fafc)', borderRadius: 8 }}>
          <div style={{ fontSize: 22, fontWeight: 700 }}>{value}</div>
          <div style={{ fontSize: 11, color: 'var(--text-muted, #64748b)' }}>{label}</div>
        </div>)}
        <div style={{ textAlign: 'center', padding: '10px 6px', background: 'var(--bg-subtle, #f8fafc)', borderRadius: 8 }}>
          <div style={{ fontSize: 18, fontWeight: 700 }}>{money(result.revenue_recorded)}</div>
          <div style={{ fontSize: 11, color: 'var(--text-muted, #64748b)' }}>Doanh thu cũ</div>
        </div>
      </div>

      {result.opted_out > 0 && <div style={{ fontSize: 13, marginTop: 12 }}>
        {result.opted_out} khách được đánh dấu <b>không liên hệ</b> theo file của phòng khám.
      </div>}

      {result.problem_count > 0 && <div style={{ marginTop: 14 }}>
        <b>{result.problem_count} dòng có vấn đề</b>
        <table className="custom-table" style={{ marginTop: 6 }}>
          <thead><tr><th style={{ width: 80 }}>Dòng</th><th>Lý do</th><th>Giá trị</th></tr></thead>
          <tbody>
            {result.problems.slice(0, 20).map((p, i) => (
              <tr key={i}><td>{p.row}</td><td>{p.reason}</td><td>{p.value}</td></tr>
            ))}
          </tbody>
        </table>
      </div>}
    </div>}
  </div>;
}
