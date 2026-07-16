(function () {
  // Config API Base URL
  const API_BASE = "http://localhost:8000/api/v1";
  let conversationId = null;

  // Insert CSS stylesheet
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = "widget.css";
  document.head.appendChild(link);

  // Create Widget Elements
  const container = document.createElement("div");
  container.id = "caredesk-widget-container";
  document.body.appendChild(container);

  // 1. Chat Launcher Button
  const launcher = document.createElement("button");
  launcher.id = "caredesk-launcher";
  launcher.innerHTML = `
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" width="28" height="28">
      <path d="M12 2C6.477 2 2 6.134 2 11.24c0 2.84 1.396 5.378 3.58 7.106-.178.966-.757 2.656-1.5 3.864 0 0-.15.244.022.3.172.056.495-.08.68-.184 1.745-.983 3.633-2.128 4.417-2.613A12.72 12.72 0 0012 20.48c5.523 0 10-4.134 10-9.24C22 6.134 17.523 2 12 2z"/>
    </svg>
  `;
  container.appendChild(launcher);

  // 2. Chat Box Window
  const chatbox = document.createElement("div");
  chatbox.id = "caredesk-chatbox";
  chatbox.style.display = "none";
  container.appendChild(chatbox);

  // 3. Setup Chatbox HTML layout
  chatbox.innerHTML = `
    <div class="caredesk-header">
      <div class="caredesk-header-info">
        <div class="caredesk-avatar">CD</div>
        <div>
          <div class="caredesk-title">Lễ tân ảo CareDesk AI</div>
          <div class="caredesk-status"><span class="status-dot"></span>Hoạt động 24/7</div>
        </div>
      </div>
      <button class="caredesk-close-btn">&times;</button>
    </div>
    
    <!-- Consent Screen -->
    <div id="caredesk-consent-screen" class="caredesk-screen">
      <div class="caredesk-consent-body">
        <p class="consent-intro">Vui lòng cung cấp thông tin để trợ lý ảo hỗ trợ bạn đặt lịch hẹn và tư vấn dịch vụ.</p>
        <div class="form-group">
          <label for="cd-name">Họ và tên *</label>
          <input type="text" id="cd-name" placeholder="Nguyễn Văn A" required>
        </div>
        <div class="form-group">
          <label for="cd-phone">Số điện thoại *</label>
          <input type="tel" id="cd-phone" placeholder="0901234567" required>
        </div>
        <div class="form-group">
          <label for="cd-email">Email (Nhận nhắc lịch)</label>
          <input type="email" id="cd-email" placeholder="example@gmail.com">
        </div>
        <div class="consent-checkbox-group">
          <input type="checkbox" id="cd-consent" value="true">
          <label for="cd-consent">Tôi đồng ý cho phép CareDesk AI lưu trữ thông tin liên hệ để đặt lịch khám.</label>
        </div>
        <button id="cd-start-chat-btn" class="cd-btn-primary" disabled>Bắt đầu trò chuyện</button>
      </div>
    </div>

    <!-- Chat Screen -->
    <div id="caredesk-chat-screen" class="caredesk-screen" style="display: none;">
      <div class="caredesk-messages-container" id="caredesk-msgs"></div>
      
      <!-- Handoff Banner -->
      <div id="caredesk-handoff-banner" class="handoff-banner" style="display: none;">
        <span>⚠️ Đang chuyển tiếp thông tin cho Lễ tân người thật hỗ trợ...</span>
      </div>

      <div class="caredesk-input-area">
        <input type="text" id="caredesk-chat-input" placeholder="Nhập tin nhắn..." autocomplete="off">
        <button id="caredesk-send-btn">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" width="20" height="20">
            <path d="M3.4 22a.8.8 0 01-.78-.96l1.62-7.04L16 12 4.24 9.98 2.62 2.96A.8.8 0 013.7 2.05l18 9a.8.8 0 010 1.9l-18 9a.8.8 0 01-.3.05z"/>
          </svg>
        </button>
      </div>
    </div>
  `;

  // Toggle Chatbox
  launcher.addEventListener("click", () => {
    if (chatbox.style.display === "none") {
      chatbox.style.display = "flex";
      launcher.style.transform = "scale(0)";
      launcher.style.opacity = "0";
    }
  });

  const closeBtn = chatbox.querySelector(".caredesk-close-btn");
  closeBtn.addEventListener("click", () => {
    chatbox.style.display = "none";
    launcher.style.transform = "scale(1)";
    launcher.style.opacity = "1";
  });

  // Handle Consent Form Validation
  const consentCheckbox = chatbox.querySelector("#cd-consent");
  const startBtn = chatbox.querySelector("#cd-start-chat-btn");
  const nameInput = chatbox.querySelector("#cd-name");
  const phoneInput = chatbox.querySelector("#cd-phone");
  const emailInput = chatbox.querySelector("#cd-email");

  function validateForm() {
    const isConsent = consentCheckbox.checked;
    const isName = nameInput.value.trim().length > 0;
    const isPhone = phoneInput.value.trim().length >= 9;
    startBtn.disabled = !(isConsent && isName && isPhone);
  }

  consentCheckbox.addEventListener("change", validateForm);
  nameInput.addEventListener("input", validateForm);
  phoneInput.addEventListener("input", validateForm);

  // Start Chat (Create Patient Lead & Conversation)
  startBtn.addEventListener("click", async () => {
    const payload = {
      full_name: nameInput.value.trim(),
      phone: phoneInput.value.trim(),
      email: emailInput.value.trim() || null,
      source: "web",
      consent_given: true
    };

    startBtn.disabled = true;
    startBtn.innerText = "Đang kết nối...";

    try {
      const response = await fetch(`${API_BASE}/chat/conversations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });

      if (!response.ok) {
        throw new Error("Không thể khởi tạo hội thoại");
      }

      const data = await response.json();
      conversationId = data.id;

      // Switch Screens
      chatbox.querySelector("#caredesk-consent-screen").style.display = "none";
      chatbox.querySelector("#caredesk-chat-screen").style.display = "flex";

      // Insert Initial Bot Welcome Message
      appendMessage("bot", `Chào bạn ${payload.full_name}, tôi là trợ lý ảo CareDesk AI. Tôi có thể giúp bạn giải đáp dịch vụ, bảng giá phòng khám hoặc hỗ trợ đặt lịch hẹn khám nhanh chóng. Bạn đang quan tâm dịch vụ nào ạ?`);
    } catch (err) {
      alert("Lỗi kết nối đến máy chủ. Vui lòng thử lại sau.");
      startBtn.disabled = false;
      startBtn.innerText = "Bắt đầu trò chuyện";
      console.error(err);
    }
  });

  // Chat Message Sending Logic
  const msgInput = chatbox.querySelector("#caredesk-chat-input");
  const sendBtn = chatbox.querySelector("#caredesk-send-btn");
  const msgsContainer = chatbox.querySelector("#caredesk-msgs");

  function appendMessage(sender, text) {
    const msgDiv = document.createElement("div");
    msgDiv.classList.add("cd-msg", `cd-msg-${sender}`);
    msgDiv.innerHTML = `
      <div class="cd-msg-bubble">${escapeHTML(text)}</div>
      <div class="cd-msg-time">${new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}</div>
    `;
    msgsContainer.appendChild(msgDiv);
    msgsContainer.scrollTop = msgsContainer.scrollHeight;
  }

  async function sendMessage() {
    const text = msgInput.value.trim();
    if (!text || !conversationId) return;

    // Clear input
    msgInput.value = "";
    appendMessage("patient", text);

    // Show Typing Indicator
    const typingDiv = document.createElement("div");
    typingDiv.id = "cd-typing";
    typingDiv.classList.add("cd-msg", "cd-msg-bot");
    typingDiv.innerHTML = `<div class="cd-msg-bubble typing-dots"><span></span><span></span><span></span></div>`;
    msgsContainer.appendChild(typingDiv);
    msgsContainer.scrollTop = msgsContainer.scrollHeight;

    try {
      const response = await fetch(`${API_BASE}/chat/conversations/${conversationId}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: text })
      });

      // Remove typing
      const typingEl = document.getElementById("cd-typing");
      if (typingEl) typingEl.remove();

      if (!response.ok) {
        throw new Error("Lỗi gửi tin nhắn");
      }

      const data = await response.json();
      appendMessage("bot", data.content);

      // Check if handoff triggered
      if (data.evaluation_metadata && data.evaluation_metadata.safety_triggered) {
        document.getElementById("caredesk-handoff-banner").style.display = "block";
        msgInput.disabled = true;
        sendBtn.disabled = true;
        msgInput.placeholder = "Hội thoại đã được chuyển cho lễ tân...";
      }
    } catch (err) {
      const typingEl = document.getElementById("cd-typing");
      if (typingEl) typingEl.remove();
      appendMessage("bot", "Rất tiếc, đã xảy ra lỗi kết nối. Vui lòng gửi lại.");
      console.error(err);
    }
  }

  sendBtn.addEventListener("click", sendMessage);
  msgInput.addEventListener("keypress", (e) => {
    if (e.key === "Enter") sendMessage();
  });

  function escapeHTML(str) {
    return str.replace(/[&<>'"]/g, 
      tag => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        "'": '&#39;',
        '"': '&quot;'
      }[tag] || tag)
    );
  }
})();
