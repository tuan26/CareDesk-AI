import { createContext, useContext, useMemo, useState } from 'react';

const COPY = {
  vi: { loading: 'Đang tải...', logout: 'Đăng xuất', bookings: 'Yêu cầu đặt lịch', dashboard: 'Tổng quan doanh thu', inbox: 'Hộp thư AI (Inbox)', appointments: 'Lịch hẹn', patients: 'Khách hàng (CRM)', packages: 'Gói liệu trình', automation: 'Tự động hóa', reports: 'Báo cáo ROI', clinic: 'Phòng khám', services: 'Dịch vụ & Giá', doctors: 'Bác sĩ & Lịch làm', settings: 'Cài đặt & AI Eval', attract: 'Thu hút & Chốt khách', retain: 'Giữ khách & Tăng doanh thu', analytics: 'Phân tích', system: 'Hệ thống' },
  en: { loading: 'Loading...', logout: 'Log out', bookings: 'Booking requests', dashboard: 'Revenue overview', inbox: 'AI inbox', appointments: 'Appointments', patients: 'Patients (CRM)', packages: 'Treatment packages', automation: 'Automation', reports: 'ROI reports', clinic: 'Clinic', services: 'Services & prices', doctors: 'Doctors & schedules', settings: 'Settings & AI evaluation', attract: 'Acquire & convert', retain: 'Retain & grow revenue', analytics: 'Analytics', system: 'System' },
  ja: { loading: '読み込み中...', logout: 'ログアウト', bookings: '予約リクエスト', dashboard: '売上概要', inbox: 'AI受信トレイ', appointments: '予約', patients: '患者（CRM）', packages: '施術パッケージ', automation: '自動化', reports: 'ROIレポート', clinic: 'クリニック', services: 'サービス・料金', doctors: '医師・勤務時間', settings: '設定・AI評価', attract: '集客・成約', retain: '顧客維持・売上向上', analytics: '分析', system: 'システム' },
};

const I18nContext = createContext(null);
export function I18nProvider({ children }) {
  const [locale, setLocaleState] = useState(() => localStorage.getItem('caredesk_locale') || 'vi');
  const setLocale = (value) => { const next = COPY[value] ? value : 'vi'; localStorage.setItem('caredesk_locale', next); setLocaleState(next); };
  const value = useMemo(() => ({ locale, setLocale, t: (key) => COPY[locale]?.[key] || COPY.en[key] || key }), [locale]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}
export const useI18n = () => useContext(I18nContext);
