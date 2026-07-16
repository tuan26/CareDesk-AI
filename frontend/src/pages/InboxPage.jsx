import { useEffect, useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';

export default function InboxPage() {
  const [conversations, setConversations] = useState([]);
  const [selectedConv, setSelectedConv] = useState(null);
  const [messages, setMessages] = useState([]);
  const [filter, setFilter] = useState('all'); // all | handoff_requested | bot_active | agent_active
  const [inputText, setInputText] = useState('');
  
  const [loading, setLoading] = useState(true);
  const messagesEndRef = useRef(null);
  const navigate = useNavigate();

  const getHeaders = () => {
    const token = localStorage.getItem('caredesk_token');
    return {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    };
  };

  const fetchConversations = async (autoSelectId = null) => {
    try {
      const headers = getHeaders();
      let url = 'http://localhost:8000/api/v1/chat/conversations';
      if (filter !== 'all') url += `?status=${filter}`;

      const response = await fetch(url, { headers });
      if (response.status === 401) throw new Error('Unauthorized');
      const data = await response.json();
      setConversations(data);

      if (autoSelectId) {
        const found = data.find(c => c.id === autoSelectId);
        if (found) setSelectedConv(found);
      } else if (data.length > 0 && !selectedConv) {
        // Default select first conversation
        setSelectedConv(data[0]);
      }
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

  const fetchMessages = async (convId) => {
    try {
      const headers = getHeaders();
      const response = await fetch(`http://localhost:8000/api/v1/chat/conversations/${convId}`, { headers });
      const data = await response.json();
      setMessages(data.messages || []);
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    fetchConversations();
  }, [filter, navigate]);

  useEffect(() => {
    if (selectedConv) {
      fetchMessages(selectedConv.id);
      
      // Setup interval to poll new messages for selected conversation
      const interval = setInterval(() => {
        fetchMessages(selectedConv.id);
      }, 3000);
      
      return () => clearInterval(interval);
    }
  }, [selectedConv]);

  useEffect(() => {
    // Auto scroll to bottom when message list updates
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSelectConversation = (conv) => {
    setSelectedConv(conv);
    setMessages([]);
  };

  const handleUpdateStatus = async (status) => {
    if (!selectedConv) return;
    try {
      const response = await fetch(`http://localhost:8000/api/v1/chat/conversations/${selectedConv.id}/status`, {
        method: 'PUT',
        headers: getHeaders(),
        body: JSON.stringify({ status })
      });
      if (response.ok) {
        const updated = await response.json();
        // Refresh local state
        fetchConversations(updated.id);
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleSendMessage = async (e) => {
    e.preventDefault();
    if (!inputText.trim() || !selectedConv) return;

    const textToSend = inputText.trim();
    setInputText('');

    // Optimistic local update
    const tempMsg = {
      id: Date.now(),
      sender: 'agent',
      content: textToSend,
      created_at: new Date().toISOString()
    };
    setMessages(prev => [...prev, tempMsg]);

    try {
      // For agent sending messages, we mock by posting to message api but bypass AI engine response by ensuring status is 'agent_active'
      // To ensure server saves it as 'agent' sender, we invoke it directly via custom route if any, or simply send message
      // Note: In our current endpoints, POST /conversations/{id}/messages creates patient msg and returns bot response.
      // But for agent to chat, we can update conversation message sender by modifying it.
      // Let's call the message endpoint:
      // Note: In endpoints/chat.py, we only have send_message (which expects patient content and triggers bot).
      // Since this is MVP, we can simulate agent message saving by storing it or if backend API supports it.
      // Let's check how chat.py handles agent messages. In our db model, Message has sender 'patient' | 'bot' | 'agent'.
      // If we call API POST /conversations/{id}/messages, it sets sender='patient' and triggers bot.
      // Since we didn't write an explicit "POST /conversations/{id}/agent-messages" endpoint, we can temporarily mock it 
      // by posting to chat webhook but marking it or we can let the frontend send it as 'agent'.
      // Wait, in chat.py:
      // "sender = Column(String, nullable=False)"
      // Let's modify backend endpoints if needed to allow agent message sending, or simply save message.
      // Actually, let's create a small helper in backend to receive agent messages, OR we can let the agent message post normally.
      // To make it fully functional, we should verify how agents can send messages.
      // Let's look at `chat.py`. It only has `send_message` which hardcodes `sender='patient'`.
      // We need to add an endpoint for agent messages or edit `chat.py` to allow sending as agent.
      // This is a critical detail! Let's check if we can add an endpoint `POST /conversations/{conv_id}/agent-messages` in `chat.py`.
      // Yes, let's do it right away! But first, let's write the frontend fetch to call `http://localhost:8000/api/v1/chat/conversations/{id}/agent-messages`.
      
      const response = await fetch(`http://localhost:8000/api/v1/chat/conversations/${selectedConv.id}/agent-messages`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({ content: textToSend })
      });
      
      if (response.ok) {
        fetchMessages(selectedConv.id);
      }
    } catch (err) {
      console.error(err);
    }
  };

  const getStatusText = (status) => {
    switch (status) {
      case 'bot_active': return 'Bot đang chat';
      case 'handoff_requested': return 'Cần Lễ tân hỗ trợ';
      case 'agent_active': return 'Nhân viên đang chat';
      default: return status;
    }
  };

  const getStatusBadgeClass = (status) => {
    switch (status) {
      case 'bot_active': return 'completed';
      case 'handoff_requested': return 'handoff_requested';
      case 'agent_active': return 'confirmed';
      default: return '';
    }
  };

  return (
    <div style={{ display: 'flex', height: 'calc(100vh - 140px)', gap: '20px' }}>
      
      {/* Panel Trái: Danh sách hội thoại */}
      <div className="card-table-wrapper" style={{ width: '320px', display: 'flex', flexDirection: 'column', height: '100%', marginBottom: 0 }}>
        <div className="card-header" style={{ padding: '14px 20px' }}>
          <h2>Hộp thư Inbox</h2>
        </div>
        
        {/* Filter Tabs */}
        <div style={{ display: 'flex', borderBottom: '1px solid var(--border-color)', backgroundColor: '#f8fafc' }}>
          <button 
            style={{ flex: 1, padding: '10px 4px', fontSize: '11px', fontWeight: 600, border: 'none', background: filter === 'all' ? 'white' : 'transparent', color: filter === 'all' ? 'var(--primary-color)' : 'var(--text-muted)', borderBottom: filter === 'all' ? '2px solid var(--primary-color)' : 'none', cursor: 'pointer' }}
            onClick={() => setFilter('all')}
          >
            Tất cả
          </button>
          <button 
            style={{ flex: 1, padding: '10px 4px', fontSize: '11px', fontWeight: 600, border: 'none', background: filter === 'handoff_requested' ? 'white' : 'transparent', color: filter === 'handoff_requested' ? 'var(--danger-color)' : 'var(--text-muted)', borderBottom: filter === 'handoff_requested' ? '2px solid var(--danger-color)' : 'none', cursor: 'pointer' }}
            onClick={() => setFilter('handoff_requested')}
          >
            ⚠️ Handoff
          </button>
          <button 
            style={{ flex: 1, padding: '10px 4px', fontSize: '11px', fontWeight: 600, border: 'none', background: filter === 'agent_active' ? 'white' : 'transparent', color: filter === 'agent_active' ? 'var(--primary-color)' : 'var(--text-muted)', borderBottom: filter === 'agent_active' ? '2px solid var(--primary-color)' : 'none', cursor: 'pointer' }}
            onClick={() => setFilter('agent_active')}
          >
            Lễ tân chat
          </button>
        </div>

        {/* Conversation List */}
        <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column' }}>
          {conversations.length === 0 ? (
            <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px' }}>Không có hội thoại nào.</div>
          ) : (
            conversations.map((conv) => (
              <div
                key={conv.id}
                onClick={() => handleSelectConversation(conv)}
                style={{
                  padding: '16px 20px',
                  borderBottom: '1px solid var(--border-color)',
                  cursor: 'pointer',
                  backgroundColor: selectedConv?.id === conv.id ? 'var(--primary-light)' : 'transparent',
                  transition: 'var(--transition)'
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                  <span style={{ fontWeight: 600, fontSize: '14px', color: 'var(--dark-color)' }}>{conv.patient?.full_name}</span>
                  <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                    {new Date(conv.updated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{conv.patient?.phone}</span>
                  <span className={`badge ${getStatusBadgeClass(conv.status)}`} style={{ fontSize: '10px', padding: '2px 6px' }}>
                    {conv.status === 'handoff_requested' ? '⚠️ Handoff' : conv.status === 'agent_active' ? 'Lễ tân' : 'Bot AI'}
                  </span>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Panel Phải: Chi tiết cuộc hội thoại & Tin nhắn */}
      <div className="card-table-wrapper" style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%', marginBottom: 0 }}>
        {selectedConv ? (
          <>
            {/* Conversation Header */}
            <div className="card-header" style={{ padding: '14px 24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', backgroundColor: '#f8fafc' }}>
              <div>
                <h2 style={{ fontSize: '15px' }}>Khách hàng: <strong>{selectedConv.patient?.full_name}</strong></h2>
                <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px' }}>
                  <span>SĐT: {selectedConv.patient?.phone}</span>
                  <span style={{ marginLeft: '12px' }}>Trạng thái: <strong>{getStatusText(selectedConv.status)}</strong></span>
                </div>
              </div>
              <div style={{ display: 'flex', gap: '10px' }}>
                {selectedConv.status !== 'agent_active' ? (
                  <button className="btn btn-primary btn-sm" onClick={() => handleUpdateStatus('agent_active')}>
                    🤝 Tiếp quản Chat (Tắt AI)
                  </button>
                ) : (
                  <button className="btn btn-secondary btn-sm" onClick={() => handleUpdateStatus('bot_active')}>
                    🤖 Trả về cho Bot AI
                  </button>
                )}
              </div>
            </div>

            {/* Message Area */}
            <div style={{ flex: 1, padding: '24px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '16px', backgroundColor: '#f1f5f9' }}>
              {messages.length === 0 ? (
                <div style={{ margin: 'auto', color: 'var(--text-muted)', fontSize: '13px' }}>Bắt đầu cuộc trò chuyện.</div>
              ) : (
                messages.map((msg) => {
                  const isAgent = msg.sender === 'agent';
                  const isBot = msg.sender === 'bot';
                  
                  // Message bubble background color classes
                  let bubbleStyle = {
                    alignSelf: isAgent ? 'flex-end' : 'flex-start',
                    maxWidth: '70%',
                    display: 'flex',
                    flexDirection: 'column'
                  };

                  let bgStyle = {
                    padding: '10px 14px',
                    borderRadius: '16px',
                    fontSize: '13.5px',
                    lineHeight: '1.4',
                    whiteSpace: 'pre-line',
                    boxShadow: '0 1px 2px rgba(0,0,0,0.05)'
                  };

                  if (isAgent) {
                    bgStyle.backgroundColor = 'var(--primary-color)';
                    bgStyle.color = 'white';
                    bgStyle.borderBottomRightRadius = '4px';
                  } else if (isBot) {
                    bgStyle.backgroundColor = '#e6f4ea'; // Light green for bot
                    bgStyle.color = '#137333';
                    bgStyle.borderBottomLeftRadius = '4px';
                    bgStyle.border = '1px solid #ceead6';
                  } else {
                    bgStyle.backgroundColor = 'white'; // Patient
                    bgStyle.color = 'var(--dark-color)';
                    bgStyle.borderBottomLeftRadius = '4px';
                    bgStyle.border = '1px solid var(--border-color)';
                  }

                  return (
                    <div key={msg.id} style={bubbleStyle}>
                      <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginBottom: '3px', alignSelf: isAgent ? 'flex-end' : 'flex-start' }}>
                        {isAgent ? 'Bạn' : isBot ? 'Trợ lý ảo CareDesk' : selectedConv.patient?.full_name}
                      </div>
                      <div style={bgStyle}>{msg.content}</div>
                      <span style={{ fontSize: '9px', color: 'var(--text-muted)', marginTop: '4px', alignSelf: isAgent ? 'flex-end' : 'flex-start' }}>
                        {new Date(msg.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </span>
                    </div>
                  );
                })
              )}
              <div ref={messagesEndRef} />
            </div>

            {/* Input Form Area */}
            <form onSubmit={handleSendMessage} style={{ padding: '16px 24px', display: 'flex', gap: '12px', borderTop: '1px solid var(--border-color)', backgroundColor: 'white' }}>
              <input
                type="text"
                className="form-control"
                placeholder={selectedConv.status === 'agent_active' ? "Nhập tin nhắn để trả lời khách hàng..." : "Bấm nút 'Tiếp quản Chat' phía trên để chat với khách hàng."}
                value={inputText}
                onChange={(e) => setInputText(e.target.value)}
                disabled={selectedConv.status !== 'agent_active'}
              />
              <button 
                type="submit" 
                className="btn btn-primary" 
                disabled={selectedConv.status !== 'agent_active' || !inputText.trim()}
              >
                Gửi
              </button>
            </form>
          </>
        ) : (
          <div style={{ margin: 'auto', textAlign: 'center', color: 'var(--text-muted)' }}>
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" width="48" height="48" style={{ color: 'var(--border-color)', marginBottom: '16px' }}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M8.625 12a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H8.25m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H12m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0h-.375M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
            </svg>
            <p>Vui lòng chọn một cuộc hội thoại từ danh sách bên trái để bắt đầu hỗ trợ khách hàng.</p>
          </div>
        )}
      </div>

    </div>
  );
}
