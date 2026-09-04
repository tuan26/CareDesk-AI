import { useEffect, useState } from 'react';
import { API_BASE, getAuthHeaders } from '../api';

const money = (value) => `${Math.round(value || 0).toLocaleString('vi-VN')}₫`;
const percent = (value) => `${Math.round((value || 0) * 100)}%`;

const CHANNEL = { zalo: 'Zalo', sms: 'SMS', call: 'Gọi điện' };

export default function MoneyPage() {
  const [leakage, setLeakage] = useState(null);
  const [performance, setPerformance] = useState(null);
  const [funnel, setFunnel] = useState(null);
  const [attribution, setAttribution] = useState(null);
  const [chain, setChain] = useState(null);
  const [queue, setQueue] = useState([]);
  const [reasons, setReasons] = useState([]);
  const [services, setServices] = useState([]);
  const [filter, setFilter] = useState('');
  const [selected, setSelected] = useState(null);
  const [outcome, setOutcome] = useState({ outcome: 'recovered', loss_reason: 'price' });
  const [showSetup, setShowSetup] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const suffix = filter ? `?type=${filter}` : '';
      const [leak, perf, fun, attr, q, reasonList, serviceList] = await Promise.all([
        fetch(`${API_BASE}/revenue/leakage`, { headers: getAuthHeaders() }),
        fetch(`${API_BASE}/revenue/performance`, { headers: getAuthHeaders() }),
        fetch(`${API_BASE}/revenue/funnel`, { headers: getAuthHeaders() }),
        fetch(`${API_BASE}/revenue/attribution`, { headers: getAuthHeaders() }),
        fetch(`${API_BASE}/revenue/queue${suffix}`, { headers: getAuthHeaders() }),
        fetch(`${API_BASE}/revenue/loss-reasons`, { headers: getAuthHeaders() }),
        fetch(`${API_BASE}/revenue/services/revisit-intervals`, { headers: getAuthHeaders() }),
      ]);
      if (!leak.ok) throw new Error('Không tải được số liệu thất thoát.');
      setLeakage(await leak.json());
      setPerformance(perf.ok ? await perf.json() : null);
      setFunnel(fun.ok ? await fun.json() : null);
      setAttribution(attr.ok ? await attr.json() : null);
      setQueue(q.ok ? (await q.json()).items : []);
      setReasons(reasonList.ok ? await reasonList.json() : []);
      setServices(serviceList.ok ? await serviceList.json() : []);
    } catch (e) { setError(e.message); } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, [filter]);

  const rescan = async () => {
    setBusy(true); setError('');
    const res = await fetch(`${API_BASE}/revenue/detect`, { method: 'POST', headers: getAuthHeaders() });
    if (!res.ok) setError((await res.json().catch(() => ({}))).detail || 'Không quét được.');
    setBusy(false); load();
  };

  const markContacted = async (item) => {
    setError('');
    const res = await fetch(`${API_BASE}/revenue/opportunities/${item.id}/contacted`, {
      method: 'POST', headers: getAuthHeaders(),
      body: JSON.stringify({ channel: item.recommended_channel }),
    });
    if (!res.ok) setError((await res.json().catch(() => ({}))).detail || 'Không cập nhật được.');
    else load();
  };

  const saveOutcome = async (event) => {
    event.preventDefault();
    setBusy(true); setError('');
    const body = { outcome: outcome.outcome };
    if (outcome.outcome === 'lost') body.loss_reason = outcome.loss_reason;
    const res = await fetch(`${API_BASE}/revenue/opportunities/${selected.id}/outcome`, {
      method: 'POST', headers: getAuthHeaders(), body: JSON.stringify(body),
    });
    if (!res.ok) setError((await res.json().catch(() => ({}))).detail || 'Không lưu được kết quả.');
    else { setSelected(null); load(); }
    setBusy(false);
  };

  const saveInterval = async (service, value) => {
    const days = value === '' ? null : Number(value);
    const res = await fetch(`${API_BASE}/revenue/services/${service.id}/revisit-interval`, {
      method: 'PUT', headers: getAuthHeaders(),
      body: JSON.stringify({ revisit_interval_days: days }),
    });
    if (res.ok) setServices((list) => list.map((s) => (s.id === service.id ? { ...s, revisit_interval_days: days } : s)));
    else setError('Chỉ chủ phòng khám mới đổi được chu kỳ tái khám.');
  };

  const openChain = async (item) => {
    const res = await fetch(`${API_BASE}/revenue/opportunities/${item.id}/chain`, { headers: getAuthHeaders() });
    if (res.ok) setChain({ ...(await res.json()), patientName: item.patient.name });
    else setError('Không tải được chuỗi truy vết.');
  };

  const copyMessage = (item) => {
    navigator.clipboard?.writeText(item.recommended_message || '');
  };

  const configured = services.filter((s) => s.revisit_interval_days).length;

  return <div>
    <div className="page-header">
      <div className="page-title">
        <h1>Doanh thu đang rơi</h1>
        <p>Những khoản phòng khám đã bỏ lỡ, xếp theo số tiền kỳ vọng thu lại được.</p>
      </div>
      <button className="btn btn-secondary" onClick={rescan} disabled={busy}>
        {busy ? 'Đang quét...' : 'Quét lại ngay'}
      </button>
    </div>

    {error && <div style={{ color: 'var(--danger-color)', marginBottom: 12 }}>{error}</div>}

    {/* The clinic has to say which treatments repeat before recall can see
        anyone. Without this prompt the dashboard just looks empty and broken. */}
    {!loading && configured === 0 && <div className="card" style={{ padding: 16, marginBottom: 16, borderLeft: '4px solid var(--warning-color, #f59e0b)' }}>
      <b>Chưa dịch vụ nào khai báo chu kỳ tái khám.</b>
      <div style={{ fontSize: 13, color: 'var(--text-muted, #64748b)', margin: '6px 0 10px' }}>
        Hệ thống không tự đoán chu kỳ — đoán sai là nhắn cho người chưa đến hạn. Khai báo xong mới tìm được khách quá hạn tái khám.
      </div>
      <button className="btn btn-primary btn-sm" onClick={() => setShowSetup(true)}>Khai báo chu kỳ</button>
    </div>}

    {loading ? <div style={{ padding: 28, textAlign: 'center' }}>Đang tải...</div> : <>
      {/* --- the headline ------------------------------------------------- */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 14, marginBottom: 18 }}>
        <div className="card" style={{ padding: 16 }}>
          <div style={{ fontSize: 12, color: 'var(--text-muted, #64748b)' }}>Có thể thu hồi (tối đa)</div>
          <div style={{ fontSize: 26, fontWeight: 700 }}>{money(leakage?.recoverable_gross)}</div>
          <div style={{ fontSize: 12, color: 'var(--text-muted, #64748b)' }}>Trần trên, không phải dự báo.</div>
        </div>
        <div className="card" style={{ padding: 16, borderLeft: '4px solid var(--primary-color, #2563eb)' }}>
          <div style={{ fontSize: 12, color: 'var(--text-muted, #64748b)' }}>Kỳ vọng thực tế</div>
          <div style={{ fontSize: 26, fontWeight: 700 }}>{money(leakage?.recoverable_expected)}</div>
          <div style={{ fontSize: 12, color: 'var(--text-muted, #64748b)' }}>Đã nhân với xác suất từng ca. Con số nên dùng để lập kế hoạch.</div>
        </div>
        <div className="card" style={{ padding: 16 }}>
          <div style={{ fontSize: 12, color: 'var(--text-muted, #64748b)' }}>Khách đã trả tiền, chưa dùng</div>
          <div style={{ fontSize: 26, fontWeight: 700 }}>{money(leakage?.at_risk_delivered)}</div>
          <div style={{ fontSize: 12, color: 'var(--text-muted, #64748b)' }}>
            Tiền đã vào két — <b>không</b> cộng vào hai ô bên trái. Rủi ro ở đây là hoàn tiền và mất khách.
          </div>
        </div>
      </div>

      {/* --- what may honestly be claimed --------------------------------- */}
      {performance && <div className="card" style={{ padding: 16, marginBottom: 18 }}>
        <h3 style={{ margin: '0 0 10px' }}>CareDesk mang lại bao nhiêu? ({performance.window_days} ngày qua)</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 14 }}>
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-muted, #64748b)' }}>Doanh thu quay lại sau khi liên hệ</div>
            <div style={{ fontSize: 20, fontWeight: 700 }}>{money(performance.gross_recovered)}</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted, #64748b)' }}>
              {performance.recovered_count}/{performance.contacted} ca. Bao gồm cả khách vốn dĩ sẽ quay lại.
            </div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-muted, #64748b)' }}>Phần thực sự nhờ CareDesk</div>
            <div style={{ fontSize: 20, fontWeight: 700 }}>
              {performance.measurable ? money(performance.net_attributable) : '—'}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted, #64748b)' }}>
              {performance.measurable
                ? `So với nhóm đối chứng ${performance.holdout_size} khách (${percent(performance.holdout_conversion)} tự quay lại).`
                : performance.measurable_note}
            </div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-muted, #64748b)' }}>ROI</div>
            <div style={{ fontSize: 20, fontWeight: 700 }}>
              {performance.roi ? `${performance.roi.toFixed(1)}x` : '—'}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted, #64748b)' }}>
              {performance.roi ? `Trên phí thuê bao ${money(performance.subscription_cost)}.` : 'Chưa đủ dữ liệu để kết luận.'}
            </div>
          </div>
        </div>
      </div>}

      {/* --- the outreach funnel ------------------------------------------ */}
      {funnel && <div className="card" style={{ padding: 16, marginBottom: 18 }}>
        <h3 style={{ margin: '0 0 4px' }}>Từ liên hệ tới tiền ({funnel.window_days} ngày qua)</h3>
        <div style={{ fontSize: 12, color: 'var(--text-muted, #64748b)', marginBottom: 12 }}>
          Mỗi bước đếm từ dữ liệu riêng của nó, không suy ra từ bước trước — nên khoảng rơi giữa hai bước là thật.
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 10 }}>
          {[
            ['Phát hiện', funnel.detected],
            ['Đã liên hệ', funnel.contacted],
            ['Có phản hồi', funnel.responded],
            ['Đã đặt lịch', funnel.booked],
            ['Đã đến khám', funnel.completed],
          ].map(([label, value]) => <div key={label} style={{ textAlign: 'center', padding: '10px 6px', background: 'var(--bg-subtle, #f8fafc)', borderRadius: 8 }}>
            <div style={{ fontSize: 22, fontWeight: 700 }}>{value}</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted, #64748b)' }}>{label}</div>
          </div>)}
          <div style={{ textAlign: 'center', padding: '10px 6px', background: 'var(--bg-subtle, #f8fafc)', borderRadius: 8 }}>
            <div style={{ fontSize: 18, fontWeight: 700 }}>{money(funnel.revenue_recovered)}</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted, #64748b)' }}>Tiền đã thu</div>
          </div>
        </div>
      </div>}

      {/* --- who gets the credit ------------------------------------------- */}
      {attribution && <div className="card-table-wrapper" style={{ marginBottom: 18 }}>
        <div className="card-header"><h2>Tiền thu về, chia theo mức độ chắc chắn</h2></div>
        <table className="custom-table">
          <thead><tr><th>Loại</th><th>Số ca</th><th>Doanh thu</th><th>Được tính cho CareDesk?</th></tr></thead>
          <tbody>
            {attribution.buckets.map((bucket) => <tr key={bucket.class}>
              <td><b>{bucket.label}</b><br /><small style={{ color: 'var(--text-muted, #64748b)' }}>
                {bucket.class === 'direct' && `Đặt lịch trong ${attribution.direct_window_days} ngày sau khi liên hệ`}
                {bucket.class === 'assisted' && `Đặt lịch muộn hơn, trong ${attribution.attribution_window_days} ngày`}
                {bucket.class === 'organic' && 'Không hề liên hệ, khách tự quay lại'}
                {bucket.class === 'unknown' && 'Ngoài cửa sổ quy kết, hoặc thiếu dữ liệu'}
              </small></td>
              <td>{bucket.count}</td>
              <td>{money(bucket.revenue)}</td>
              <td>{['direct', 'assisted'].includes(bucket.class)
                ? <span className="badge completed">Có</span>
                : <span className="badge pending">Không</span>}</td>
            </tr>)}
          </tbody>
        </table>
        <div style={{ padding: '10px 16px', fontSize: 12, color: 'var(--text-muted, #64748b)' }}>
          Chỉ <b>{money(attribution.attributable_revenue)}</b> được phép gọi là doanh thu CareDesk mang về.
          {' '}{money(attribution.organic_revenue)} là khách tự quay lại — hiện ở đây để tổng khớp, không phải để cộng vào.
        </div>
      </div>}

      {/* --- buckets ------------------------------------------------------ */}
      <div className="card-table-wrapper" style={{ marginBottom: 18 }}>
        <div className="card-header"><h2>Tiền rơi ở đâu</h2></div>
        <table className="custom-table">
          <thead><tr><th>Nhóm</th><th>Số ca</th><th>Giá trị</th><th>Kỳ vọng</th><th>Xác suất</th><th></th></tr></thead>
          <tbody>
            {(leakage?.buckets || []).map((bucket) => <tr key={bucket.type}>
              <td><b>{bucket.label}</b>{bucket.value_kind === 'at_risk_delivered' && <><br /><small style={{ color: 'var(--text-muted, #64748b)' }}>Khách đã trả tiền</small></>}</td>
              <td>{bucket.count}</td>
              <td>{money(bucket.gross_value)}</td>
              <td>{money(bucket.expected_value)}</td>
              <td><span className={`badge ${bucket.probability_is_measured ? 'completed' : 'pending'}`}>
                {bucket.probability_is_measured ? 'Đo thực tế' : 'Giả định'}
              </span></td>
              <td><button className="btn btn-secondary btn-sm" onClick={() => setFilter(bucket.type)}>Xem</button></td>
            </tr>)}
            {(leakage?.buckets || []).length === 0 && <tr><td colSpan={6} style={{ padding: 24, textAlign: 'center' }}>Chưa phát hiện khoản nào. Bấm "Quét lại ngay".</td></tr>}
          </tbody>
        </table>
        <div style={{ padding: '10px 16px', fontSize: 12, color: 'var(--text-muted, #64748b)' }}>{leakage?.holdout_note}</div>
      </div>

      {/* --- the money queue ---------------------------------------------- */}
      <div className="card-table-wrapper">
        <div className="card-header" style={{ gap: 12 }}>
          <h2>Việc hôm nay ({queue.length})</h2>
          <select className="form-control" style={{ width: 220 }} value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">Tất cả các nhóm</option>
            {(leakage?.buckets || []).map((b) => <option key={b.type} value={b.type}>{b.label}</option>)}
          </select>
        </div>
        <table className="custom-table">
          <thead><tr><th>Khách</th><th>Vì sao</th><th>Giá trị</th><th>Khả năng</th><th>Kênh</th><th>Thao tác</th></tr></thead>
          <tbody>
            {queue.map((item) => <tr key={item.id}>
              <td><b>{item.patient.name}</b><br /><small>{item.patient.phone || 'Chưa có số'}</small></td>
              <td>{item.type_label}<br /><small style={{ color: 'var(--text-muted, #64748b)' }}>
                {item.service_name} · {item.urgency_days} ngày
              </small></td>
              <td>{money(item.estimated_value)}<br /><small>kỳ vọng {money(item.expected_value)}</small></td>
              <td>
                <b>{percent(item.probability)}</b>
                {/* Reasons are the whole reason staff trust the ordering. */}
                <div style={{ fontSize: 11, color: 'var(--text-muted, #64748b)' }}>
                  {(item.reasons || []).slice(0, 2).map((r) => r.text).join(' · ')}
                </div>
              </td>
              <td>{CHANNEL[item.recommended_channel] || item.recommended_channel}</td>
              <td><div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                <button className="btn btn-secondary btn-sm" onClick={() => copyMessage(item)}>Chép tin nhắn</button>
                {item.status === 'open' && <button className="btn btn-primary btn-sm" onClick={() => markContacted(item)}>Đã liên hệ</button>}
                <button className="btn btn-secondary btn-sm" onClick={() => { setSelected(item); setOutcome({ outcome: 'recovered', loss_reason: 'price' }); }}>Kết quả</button>
                <button className="btn btn-secondary btn-sm" onClick={() => openChain(item)}>Truy vết</button>
              </div></td>
            </tr>)}
            {queue.length === 0 && <tr><td colSpan={6} style={{ padding: 24, textAlign: 'center' }}>Không còn việc nào trong nhóm này.</td></tr>}
          </tbody>
        </table>
      </div>
    </>}

    {/* --- outcome ------------------------------------------------------- */}
    {selected && <div className="modal-overlay" onClick={() => setSelected(null)}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header"><h3>Kết quả: {selected.patient.name}</h3>
          <button className="modal-close-btn" onClick={() => setSelected(null)}>&times;</button></div>
        <form onSubmit={saveOutcome}>
          <div className="modal-body">
            <p style={{ fontSize: 13, color: 'var(--text-muted, #64748b)' }}>
              Ghi lại kết quả để hệ thống học tỷ lệ thật của phòng khám, thay cho con số giả định.
            </p>
            <div className="form-group"><label>Kết quả</label>
              <select className="form-control" value={outcome.outcome}
                      onChange={(e) => setOutcome({ ...outcome, outcome: e.target.value })}>
                <option value="recovered">Đã quay lại / đã đặt lịch</option>
                <option value="lost">Không thành</option>
                <option value="dismissed">Bỏ qua ca này</option>
              </select>
            </div>
            {outcome.outcome === 'lost' && <div className="form-group"><label>Vì sao mất?</label>
              <select className="form-control" value={outcome.loss_reason}
                      onChange={(e) => setOutcome({ ...outcome, loss_reason: e.target.value })}>
                {reasons.map((r) => <option key={r.code} value={r.code}>{r.label}</option>)}
              </select>
            </div>}
          </div>
          <div className="modal-footer">
            <button type="button" className="btn btn-secondary" onClick={() => setSelected(null)}>Đóng</button>
            <button type="submit" className="btn btn-primary" disabled={busy}>Lưu</button>
          </div>
        </form>
      </div>
    </div>}

    {/* --- the attribution chain ----------------------------------------- */}
    {chain && <div className="modal-overlay" onClick={() => setChain(null)}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header"><h3>Truy vết: {chain.patientName}</h3>
          <button className="modal-close-btn" onClick={() => setChain(null)}>&times;</button></div>
        <div className="modal-body">
          <p style={{ fontSize: 13, color: 'var(--text-muted, #64748b)' }}>
            Con số nào cũng phải lần ngược được tới buổi khám và phiếu thu, nếu không thì chỉ còn cách tin hoặc bỏ qua.
          </p>
          <table className="custom-table">
            <tbody>
              <tr><td>Cơ hội</td><td>#{chain.opportunity_id} · {chain.status}
                {chain.is_holdout && <span className="badge pending" style={{ marginLeft: 6 }}>Nhóm đối chứng</span>}</td></tr>
              {chain.actions.map((a) => <tr key={a.id}>
                <td>Liên hệ #{a.id}</td>
                <td>{CHANNEL[a.channel] || a.channel}
                  {a.template_code && ` · ${a.template_code}`}
                  {a.responded_at ? ' · khách đã trả lời' : ' · chưa thấy phản hồi'}</td>
              </tr>)}
              {chain.actions.length === 0 && <tr><td>Liên hệ</td><td style={{ color: 'var(--text-muted, #64748b)' }}>Chưa liên hệ lần nào</td></tr>}
              <tr><td>Lịch hẹn</td><td>{chain.appointment ? `#${chain.appointment.id} · ${chain.appointment.status}` : '—'}</td></tr>
              <tr><td>Phiếu thu</td><td>{chain.revenue_record ? `#${chain.revenue_record.id} · ${money(chain.revenue_record.amount)}` : '—'}</td></tr>
              <tr><td><b>Tiền thu về</b></td><td><b>{chain.revenue_recovered === null ? 'Chưa có' : money(chain.revenue_recovered)}</b></td></tr>
              <tr><td>Quy kết</td><td>{chain.attribution_class
                ? { direct: 'Trực tiếp', assisted: 'Gián tiếp', organic: 'Khách tự quay lại', unknown: 'Không xác định' }[chain.attribution_class]
                : '—'}</td></tr>
            </tbody>
          </table>
        </div>
        <div className="modal-footer">
          <button className="btn btn-secondary" onClick={() => setChain(null)}>Đóng</button>
        </div>
      </div>
    </div>}

    {/* --- revisit intervals --------------------------------------------- */}
    {showSetup && <div className="modal-overlay" onClick={() => setShowSetup(false)}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header"><h3>Chu kỳ tái khám theo dịch vụ</h3>
          <button className="modal-close-btn" onClick={() => setShowSetup(false)}>&times;</button></div>
        <div className="modal-body">
          <p style={{ fontSize: 13, color: 'var(--text-muted, #64748b)' }}>
            Để trống nghĩa là dịch vụ làm một lần — hệ thống sẽ không bao giờ nhắc tái khám cho dịch vụ đó.
          </p>
          <table className="custom-table">
            <thead><tr><th>Dịch vụ</th><th style={{ width: 150 }}>Lặp lại sau (ngày)</th></tr></thead>
            <tbody>
              {services.map((service) => <tr key={service.id}>
                <td>{service.name}</td>
                <td><input className="form-control" type="number" min={1} max={1095}
                           defaultValue={service.revisit_interval_days || ''}
                           placeholder="không lặp"
                           onBlur={(e) => saveInterval(service, e.target.value)} /></td>
              </tr>)}
            </tbody>
          </table>
        </div>
        <div className="modal-footer">
          <button className="btn btn-primary" onClick={() => { setShowSetup(false); rescan(); }}>Xong, quét lại</button>
        </div>
      </div>
    </div>}
  </div>;
}
