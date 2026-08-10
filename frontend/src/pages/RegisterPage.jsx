import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { API_BASE } from '../api';
import './Login.css';

export default function RegisterPage() {
  const navigate = useNavigate();
  const [form, setForm] = useState({
    clinic_name: '', owner_name: '', email: '', password: '', phone: '', address: ''
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (form.password.length < 6) {
      setError('Mật khẩu cần ít nhất 6 ký tự.');
      return;
    }
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/auth/register-clinic`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          clinic_name: form.clinic_name,
          owner_name: form.owner_name,
          email: form.email,
          password: form.password,
          phone: form.phone || null,
          address: form.address || null
        })
      });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(data?.detail || 'Không thể đăng ký. Vui lòng thử lại.');
      }
      const data = await res.json();
      localStorage.setItem('caredesk_token', data.access_token);
      // Straight into setup: an empty dashboard is where new clinics stall.
      navigate('/onboarding');
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const setField = (field) => (e) => setForm({ ...form, [field]: e.target.value });

  return (
    <div className="login-page">
      <div className="login-card" style={{ width: '480px' }}>
        <div className="login-logo">
          <div className="login-logo-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
            </svg>
          </div>
          <span className="login-logo-text">CareDesk</span>
        </div>

        <div className="login-heading">
          <h2>Đăng ký phòng khám</h2>
          <p>Tạo tài khoản miễn phí — gói Free gồm 200 hội thoại AI/tháng</p>
        </div>

        {error && (
          <div className="login-error">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
            <span>{error}</span>
          </div>
        )}

        <form className="login-form" onSubmit={handleSubmit}>
          <div className="login-field">
            <label>Tên phòng khám *</label>
            <div className="login-input-wrapper">
              <input className="login-input" value={form.clinic_name} onChange={setField('clinic_name')}
                placeholder="Phòng khám Da liễu ABC" required autoFocus />
            </div>
          </div>
          <div className="login-field">
            <label>Họ tên chủ phòng khám *</label>
            <div className="login-input-wrapper">
              <input className="login-input" value={form.owner_name} onChange={setField('owner_name')}
                placeholder="Nguyễn Văn A" required />
            </div>
          </div>
          <div className="login-field">
            <label>Email đăng nhập *</label>
            <div className="login-input-wrapper">
              <input className="login-input" type="email" value={form.email} onChange={setField('email')}
                placeholder="you@example.com" required autoComplete="email" />
            </div>
          </div>
          <div className="login-field">
            <label>Mật khẩu *</label>
            <div className="login-input-wrapper">
              <input className="login-input" type="password" value={form.password} onChange={setField('password')}
                placeholder="Ít nhất 6 ký tự" required autoComplete="new-password" />
            </div>
          </div>
          <div className="login-field">
            <label>Số điện thoại</label>
            <div className="login-input-wrapper">
              <input className="login-input" value={form.phone} onChange={setField('phone')} placeholder="0901234567" />
            </div>
          </div>
          <div className="login-field">
            <label>Địa chỉ phòng khám</label>
            <div className="login-input-wrapper">
              <input className="login-input" value={form.address} onChange={setField('address')}
                placeholder="123 Đường ABC, Quận 1, TP.HCM" />
            </div>
          </div>

          <button type="submit" className="login-submit" disabled={loading}>
            {loading && <span className="spinner" />}
            {loading ? 'Đang tạo tài khoản...' : 'Đăng ký miễn phí'}
          </button>
        </form>

        <div className="login-footer">
          Đã có tài khoản? <Link to="/login" style={{ fontWeight: 600 }}>Đăng nhập</Link>
        </div>
      </div>
    </div>
  );
}
