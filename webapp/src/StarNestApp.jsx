import React, { useEffect, useState, useCallback, useRef } from "react";

const API_URL = import.meta.env.VITE_API_URL || "";
const USER_TOKEN_KEY = "starnest_user_token";
const ADMIN_TOKEN_KEY = "starnest_admin_token";
// Referal havolasi uchun bot username (build vaqtida VITE_BOT_USERNAME orqali beriladi)
const BOT_USERNAME = (import.meta.env.VITE_BOT_USERNAME || "Star_NestBot").replace(/^@/, "");

// ---------------------------------------------------------------------------
// Yordamchilar
// ---------------------------------------------------------------------------
const ERROR_TEXTS = {
  insufficient_balance: "Balansingiz yetarli emas. Avval balansni to'ldiring.",
  force_sub: "Avval botdagi kanallarga obuna bo'ling.",
  invalid_recipient: "Username noto'g'ri. Masalan: @username",
  username_required: "Telegram profilingizda username yo'q. \"Boshqaga\" ni tanlab, username kiriting.",
  invalid_quantity: "Stars miqdori noto'g'ri yoki minimaldan kam.",
  invalid_price: "Narx hozir noto'g'ri sozlangan. Admin bilan bog'laning.",
  not_pending: "Bu so'rov allaqachon hal qilingan.",
  not_found: "Topilmadi.",
  invalid_amount: "Summa noto'g'ri.",
  too_many_attempts: "Juda ko'p urinish. Bir necha daqiqadan keyin qayta urinib ko'ring.",
  too_many_pending: "Sizda tekshirilmagan so'rovlar ko'p. Avval ular ko'rib chiqilishini kuting.",
  file_too_large: "Fayl juda katta (5 MB gacha bo'lishi kerak).",
  invalid_file: "Faqat JPG, PNG yoki WEBP rasm yuboring.",
  receipt_required: "Chek rasmini tanlang.",
  receipt_failed: "Chek yuborilmadi. Birozdan keyin qayta urinib ko'ring.",
  already_running: "Boshqa xabar hozir yuborilmoqda.",
  weak_password: "Parol kamida 8 belgi bo'lishi va oddiy (masalan, admin) bo'lmasligi kerak.",
  wrong_password: "Joriy parol noto'g'ri.",
  invalid_login: "Login 3-32 belgi bo'lsin: harf, raqam, _ . -",
  "already exists": "Bu login band.",
  block_id_required: "Bonusni yoqish uchun AdsGram Block ID kiriting.",
  invalid_block_id: "Block ID noto'g'ri.",
  blocked: "Siz bloklangansiz.",
  send_failed: "Xabar yuborilmadi.",
};

function errText(e) {
  const code = e?.data?.error;
  if (code && ERROR_TEXTS[code]) return ERROR_TEXTS[code];
  if (code && code.startsWith("invalid_")) return `Qiymat noto'g'ri (${code.slice(8)})`;
  return "Xatolik yuz berdi, qayta urinib ko'ring.";
}

// 0.0020 -> "0.002"
function fmtUsd(v, digits = 4) {
  const n = Number(v);
  return Number.isFinite(n) ? String(parseFloat(n.toFixed(digits))) : "0";
}

function fmtCountdown(sec) {
  const s = Math.max(0, Math.floor(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

// ---------------------------------------------------------------------------
// API helper
//  - reauth: 401 kelganda tokenni yangilab (foydalanuvchi uchun initData bilan) so'rovni bir marta takrorlaydi
//  - onUnauthorized: sessiya tugagani aniq bo'lsa chaqiriladi (admin panel login oynasiga qaytadi)
// ---------------------------------------------------------------------------
function useApi(tokenKey, { reauth, onUnauthorized } = {}) {
  const hooks = useRef({});
  hooks.current = { reauth, onUnauthorized };

  return useCallback(
    async function callApi(path, { method = "GET", body, isForm = false } = {}, retried = false) {
      const token = localStorage.getItem(tokenKey);
      const headers = {};
      if (!isForm) headers["Content-Type"] = "application/json";
      if (token) headers["Authorization"] = `Bearer ${token}`;

      const res = await fetch(`${API_URL}${path}`, {
        method,
        headers,
        body: isForm ? body : body ? JSON.stringify(body) : undefined,
      });

      let data = null;
      try {
        data = await res.json();
      } catch {
        data = null;
      }

      const isAuthCall = path === "/api/auth" || path === "/api/admin/login";
      if (res.status === 401 && !isAuthCall) {
        if (!retried && hooks.current.reauth && (await hooks.current.reauth())) {
          return callApi(path, { method, body, isForm }, true);
        }
        hooks.current.onUnauthorized?.();
      }

      if (!res.ok) {
        const err = new Error((data && data.error) || `HTTP ${res.status}`);
        err.status = res.status;
        err.data = data;
        throw err;
      }
      return data;
    },
    [tokenKey]
  );
}

function Toast({ message, onDone }) {
  const doneRef = useRef(onDone);
  doneRef.current = onDone;
  useEffect(() => {
    if (!message) return;
    const t = setTimeout(() => doneRef.current?.(), 2600);
    return () => clearTimeout(t);
  }, [message]);
  if (!message) return null;
  return <div className="toast">{message}</div>;
}

function Avatar({ photoUrl, name, size = 56 }) {
  const initial = (name || "?").trim().charAt(0).toUpperCase() || "?";
  return (
    <div className="avatar-ring" style={{ width: size, height: size }}>
      {photoUrl ? (
        <img src={photoUrl} alt="" />
      ) : (
        <div className="avatar-fallback" style={{ fontSize: size * 0.4 }}>
          {initial}
        </div>
      )}
    </div>
  );
}

function StatusPill({ status }) {
  const labels = { pending: "Kutilmoqda", approved: "Tasdiqlandi", cancelled: "Bekor qilindi", rejected: "Rad etildi" };
  return <span className={`pill pill-${status}`}>{labels[status] || status}</span>;
}

// ---------------------------------------------------------------------------
// Root
// ---------------------------------------------------------------------------
export default function StarNestApp() {
  const isAdmin = new URLSearchParams(window.location.search).get("admin") === "1";
  return isAdmin ? <AdminApp /> : <UserApp />;
}

function UserApp() {
  // Token eskirgan bo'lsa Telegram initData bilan jimgina yangilanadi
  const reauth = useCallback(async () => {
    const initData = window.Telegram?.WebApp?.initData || "";
    if (!initData) return false;
    try {
      const res = await fetch(`${API_URL}/api/auth`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initData }),
      });
      if (!res.ok) return false;
      const d = await res.json();
      localStorage.setItem(USER_TOKEN_KEY, d.token);
      return true;
    } catch {
      return false;
    }
  }, []);

  const api = useApi(USER_TOKEN_KEY, { reauth });
  const [user, setUser] = useState(null);
  const [pricing, setPricing] = useState(null);
  const [tab, setTab] = useState("home");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [toast, setToast] = useState("");

  const refreshMe = useCallback(async () => {
    try {
      const data = await api("/api/me");
      setUser(data.user);
    } catch {
      /* jim */
    }
  }, [api]);

  useEffect(() => {
    let interval;
    let tick;
    let cancelled = false;

    async function boot() {
      try {
        const tg = window.Telegram?.WebApp;
        const initData = tg?.initData || "";
        if (!initData) {
          setError("Bu ilova faqat Telegram ichida, inline tugma orqali ochilganda ishlaydi.");
          setLoading(false);
          return;
        }
        const authData = await api("/api/auth", { method: "POST", body: { initData } });
        localStorage.setItem(USER_TOKEN_KEY, authData.token);
        setUser(authData.user);
        const pricingData = await api("/api/pricing");
        setPricing(pricingData);
        setLoading(false);
        if (cancelled) return;

        // Balansni 15 soniyada bir marta (va ilova qayta ko'ringanda) yangilaymiz — faqat ekran ochiq bo'lsa
        tick = () => {
          if (document.visibilityState === "visible") refreshMe();
        };
        interval = setInterval(tick, 15000);
        document.addEventListener("visibilitychange", tick);
      } catch (e) {
        setError(e.data?.error === "blocked" ? "Siz bloklangansiz." : "Kirishda xatolik yuz berdi.");
        setLoading(false);
      }
    }
    boot();
    return () => {
      cancelled = true;
      if (interval) clearInterval(interval);
      if (tick) document.removeEventListener("visibilitychange", tick);
    };
  }, [api, refreshMe]);

  if (loading) {
    return (
      <div className="app-shell">
        <div className="spinner" />
      </div>
    );
  }
  if (error) {
    return (
      <div className="app-shell">
        <div className="card">{error}</div>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <Toast message={toast} onDone={() => setToast("")} />
      <Header user={user} />
      {tab === "home" && <HomeTab api={api} user={user} pricing={pricing} setToast={setToast} setUser={setUser} />}
      {tab === "bonus" && <BonusTab api={api} setToast={setToast} refreshMe={refreshMe} />}
      {tab === "balance" && <BalanceTab api={api} user={user} pricing={pricing} setToast={setToast} refreshMe={refreshMe} />}
      {tab === "orders" && <OrdersTab api={api} />}
      {tab === "referral" && <ReferralTab api={api} user={user} />}
      <TabBar tab={tab} setTab={setTab} />
    </div>
  );
}

function Header({ user }) {
  if (!user) return null;
  return (
    <div className="card row">
      <div className="row" style={{ gap: 12 }}>
        <Avatar photoUrl={user.photo_url} name={user.first_name} />
        <div>
          <div style={{ fontFamily: "Sora", fontWeight: 700 }}>{user.first_name || "Foydalanuvchi"}</div>
          <div className="muted">{user.username ? `@${user.username}` : `ID: ${user.user_id}`}</div>
        </div>
      </div>
      <div style={{ textAlign: "right" }}>
        <div className="muted">Balans</div>
        <div className="mono" style={{ fontSize: 20, fontWeight: 600, color: "var(--gold)" }}>
          ${Number(user.balance).toFixed(2)}
        </div>
      </div>
    </div>
  );
}

function HomeTab({ api, user, pricing, setToast, setUser }) {
  const minQty = pricing?.min_stars_quantity || 50;
  const [mode, setMode] = useState("stars"); // stars | premium
  const [qtyText, setQtyText] = useState(String(minQty));
  const [duration, setDuration] = useState("3");
  const [recipientMode, setRecipientMode] = useState("self"); // self | other
  const [recipient, setRecipient] = useState("");
  const [submitting, setSubmitting] = useState(false);

  if (!pricing) return null;

  const qty = parseInt(qtyText, 10);
  const qtyValid = Number.isInteger(qty) && qty >= minQty && qty <= 100000;
  const price =
    mode === "stars"
      ? (qtyValid ? qty : 0) * pricing.stars_price_per_unit
      : pricing[`premium_price_${duration}m`];
  const canAfford = user && user.balance >= price;

  // O'zimga — foydalanuvchining o'z username'i; Boshqaga — kiritilgan username
  const ownUsername = user?.username ? `@${user.username}` : "";
  const effectiveRecipient = recipientMode === "other" ? recipient.trim() : ownUsername;
  const recipientValid = /^@?[A-Za-z0-9_]{3,32}$/.test(effectiveRecipient);
  const quantityOk = mode === "premium" || qtyValid;

  async function submit() {
    setSubmitting(true);
    try {
      const body =
        mode === "stars"
          ? { type: "stars", quantity: qty, recipient: effectiveRecipient }
          : { type: "premium", duration, recipient: effectiveRecipient };
      const res = await api("/api/orders", { method: "POST", body });
      setToast(`Buyurtma yaratildi: ${res.order.id}`);
      const me = await api("/api/me");
      setUser(me.user);
    } catch (e) {
      setToast(errText(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="card">
      <div className="grid-2">
        <button className={mode === "stars" ? "btn btn-primary" : "btn btn-secondary"} onClick={() => setMode("stars")}>
          <span className="btn-icon-label"><Icon name="star" size={16} />Stars</span>
        </button>
        <button className={mode === "premium" ? "btn btn-purple" : "btn btn-secondary"} onClick={() => setMode("premium")}>
          <span className="btn-icon-label"><Icon name="gem" size={16} />Premium</span>
        </button>
      </div>

      {mode === "stars" ? (
        <>
          <label>Miqdor (dona, kamida {minQty})</label>
          <input
            type="number"
            inputMode="numeric"
            min={minQty}
            value={qtyText}
            onChange={(e) => setQtyText(e.target.value)}
            onBlur={() => { if (!qtyValid) setQtyText(String(minQty)); }}
          />
          {!qtyValid && qtyText !== "" && (
            <p style={{ color: "var(--danger)", fontSize: 12, marginTop: 6 }}>Kamida {minQty} ta Stars sotib olinadi.</p>
          )}
          <div className="grid-2" style={{ marginTop: 8 }}>
            {[minQty, minQty * 2, minQty * 5, minQty * 10].map((n) => (
              <button key={n} className="btn btn-secondary" onClick={() => setQtyText(String(n))}>
                {n}
              </button>
            ))}
          </div>
        </>
      ) : (
        <>
          <label>Muddat</label>
          <div className="grid-2">
            {["3", "6", "9", "12"].map((d) => (
              <div key={d} className={`duration-chip ${duration === d ? "selected" : ""}`} onClick={() => setDuration(d)}>
                <div style={{ fontWeight: 700 }}>{d} oy</div>
                <div className="muted mono">${pricing[`premium_price_${d}m`]}</div>
              </div>
            ))}
          </div>
        </>
      )}

      <label>Kimga</label>
      <div className="grid-2">
        <button className={recipientMode === "self" ? "btn btn-primary" : "btn btn-secondary"} onClick={() => setRecipientMode("self")}>
          O'zimga
        </button>
        <button className={recipientMode === "other" ? "btn btn-primary" : "btn btn-secondary"} onClick={() => setRecipientMode("other")}>
          Boshqaga
        </button>
      </div>
      {recipientMode === "self" ? (
        ownUsername ? (
          <p className="muted" style={{ marginTop: 8 }}>
            <span className="mono" style={{ color: "var(--gold)" }}>{ownUsername}</span> ga yetkaziladi.
          </p>
        ) : (
          <p style={{ color: "var(--danger)", fontSize: 13, marginTop: 8 }}>
            Telegram profilingizda username yo'q. "Boshqaga" ni tanlab, username kiriting yoki profilingizda username o'rnating.
          </p>
        )
      ) : (
        <input style={{ marginTop: 8 }} placeholder="@username" value={recipient} onChange={(e) => setRecipient(e.target.value)} />
      )}

      <div className="divider" />
      <div className="row">
        <span className="muted">Jami narx</span>
        <span className="mono" style={{ fontSize: 18, fontWeight: 700, color: "var(--gold)" }}>
          ${price.toFixed(2)}
        </span>
      </div>

      <div style={{ marginTop: 14 }}>
        <button className="btn btn-primary" disabled={submitting || !canAfford || !recipientValid || !quantityOk} onClick={submit}>
          {submitting ? "Yuborilmoqda..." : canAfford ? "Sotib olish" : "Balans yetarli emas"}
        </button>
      </div>
    </div>
  );
}

function BalanceTab({ api, user, pricing, setToast, refreshMe }) {
  const [showTopup, setShowTopup] = useState(false);
  return (
    <>
      <div className="card" style={{ textAlign: "center", padding: "28px 18px" }}>
        <div className="muted">Joriy balans</div>
        <div className="mono" style={{ fontSize: 34, fontWeight: 700, color: "var(--gold)", margin: "8px 0" }}>
          ${user ? Number(user.balance).toFixed(2) : "0.00"}
        </div>
        <button className="btn btn-primary" onClick={() => setShowTopup(true)}>
          Balansni to'ldirish
        </button>
      </div>
      {showTopup && (
        <TopupModal
          api={api}
          user={user}
          pricing={pricing}
          setToast={setToast}
          onClose={() => setShowTopup(false)}
          onDone={async () => {
            setShowTopup(false);
            setToast("Chek yuborildi, admin tez orada tekshiradi.");
            await refreshMe();
          }}
        />
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Balansni to'ldirish — ikki bosqich:
//  • Summa: foydalanuvchi USD miqdorini tanlaydi/kiritadi, kurs bo'yicha so'm ekvivalenti,
//    joriy kurs va Telegram username'i ko'rsatiladi — "Tasdiqlash" bilan davom etadi.
//  • To'lov: karta raqami (admin kiritgan) ko'rsatiladi, chek yuklanadi, "To'ladim" bosiladi.
// ---------------------------------------------------------------------------
const TOPUP_QUICK_AMOUNTS = [1, 3, 5, 10, 20];

function TopupModal({ api, user, pricing, setToast, onClose, onDone }) {
  const [step, setStep] = useState(1);
  const [amount, setAmount] = useState("5");
  const [file, setFile] = useState(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const MAX_BYTES = 5 * 1024 * 1024;

  const rate = pricing?.usd_to_uzs_rate || 0;
  const cardNumber = pricing?.topup_card_number || "";
  const cardHolder = pricing?.topup_card_holder || "";
  const amountNum = parseFloat(amount) || 0;
  const uzsAmount = Math.round(amountNum * rate);
  const maxTopup = pricing?.max_topup_usd || 10000;
  const amountTooBig = amountNum > maxTopup;
  const canContinue = amountNum > 0 && !amountTooBig && !!cardNumber;

  function pickFile(e) {
    const f = e.target.files?.[0] || null;
    setError("");
    if (f && f.size > MAX_BYTES) {
      setFile(null);
      setError(errText({ data: { error: "file_too_large" } }));
      return;
    }
    setFile(f);
  }

  function copyCard() {
    navigator.clipboard?.writeText(cardNumber);
    setToast?.("Karta raqami nusxalandi");
  }

  async function submit() {
    if (!file || sending) return;
    setSending(true);
    setError("");
    try {
      const form = new FormData();
      form.append("amount_usd", String(amountNum));
      form.append("receipt", file);
      await api("/api/payments", { method: "POST", body: form, isForm: true });
      onDone();
    } catch (e) {
      setError(errText(e));
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-sheet" onClick={(e) => e.stopPropagation()}>
        {step === 1 ? (
          <>
            <h3>Balansni to'ldirish</h3>
            <p className="muted" style={{ marginTop: 6 }}>To'ldirmoqchi bo'lgan summani tanlang.</p>

            <div className="grid-2" style={{ marginTop: 12 }}>
              {TOPUP_QUICK_AMOUNTS.map((n) => (
                <button
                  key={n}
                  className={String(n) === amount ? "btn btn-primary" : "btn btn-secondary"}
                  onClick={() => setAmount(String(n))}
                >
                  ${n}
                </button>
              ))}
            </div>
            <label>Yoki boshqa summa (USD)</label>
            <input type="number" min="1" value={amount} onChange={(e) => setAmount(e.target.value)} />

            <div className="info-list">
              <div className="info-row">
                <span className="muted">Kurs</span>
                <span className="mono">1$ = {rate ? rate.toLocaleString("ru-RU") : "—"} so'm</span>
              </div>
              <div className="info-row">
                <span className="muted">Siz kiritgan summa</span>
                <span className="mono">${amountNum.toFixed(2)}</span>
              </div>
              <div className="info-row" style={{ borderTop: "1px solid var(--glass-border)", paddingTop: 8 }}>
                <span className="muted">So'mda to'lanadigan summa</span>
                <span className="mono" style={{ fontWeight: 700, color: "var(--gold)" }}>
                  {uzsAmount.toLocaleString("ru-RU")} so'm
                </span>
              </div>
              <div className="info-row">
                <span className="muted">Telegram</span>
                <span className="mono">{user?.username ? `@${user.username}` : `ID: ${user?.user_id}`}</span>
              </div>
            </div>

            {amountTooBig && (
              <p style={{ color: "var(--danger)", fontSize: 13, marginTop: 10 }}>
                Bir martada ko'pi bilan ${maxTopup} to'ldirish mumkin.
              </p>
            )}
            {!cardNumber && (
              <p style={{ color: "var(--danger)", fontSize: 13, marginTop: 10 }}>
                Hozircha to'lov kartasi sozlanmagan. Admin bilan bog'laning.
              </p>
            )}

            <div className="grid-2" style={{ marginTop: 16 }}>
              <button className="btn btn-secondary" onClick={onClose}>
                Bekor qilish
              </button>
              <button className="btn btn-primary" disabled={!canContinue} onClick={() => setStep(2)}>
                Tasdiqlash
              </button>
            </div>
          </>
        ) : (
          <>
            <h3>To'lov</h3>
            <p className="muted" style={{ marginTop: 6 }}>
              Quyidagi kartaga <b className="mono">{uzsAmount.toLocaleString("ru-RU")} so'm</b> o'tkazing, chekni yuklab
              "To'ladim" tugmasini bosing.
            </p>

            <div className="card" style={{ margin: "12px 0 0", background: "rgba(255,255,255,0.06)" }}>
              <div className="muted" style={{ fontSize: 12 }}>Karta raqami</div>
              <div className="row" style={{ marginTop: 4 }}>
                <span className="mono" style={{ fontSize: 18, letterSpacing: 1 }}>{cardNumber}</span>
                <button className="btn btn-secondary" style={{ width: "auto", padding: "6px 12px" }} onClick={copyCard}>
                  Nusxalash
                </button>
              </div>
              {cardHolder && <div className="muted" style={{ marginTop: 6 }}>{cardHolder}</div>}
            </div>

            <label>To'lov chekining rasmi (JPG, PNG yoki WEBP, 5 MB gacha)</label>
            <input type="file" accept="image/jpeg,image/png,image/webp" onChange={pickFile} />
            {error && <div style={{ color: "var(--danger)", marginTop: 10 }}>{error}</div>}

            <div className="grid-2" style={{ marginTop: 16 }}>
              <button className="btn btn-secondary" onClick={() => setStep(1)}>
                Orqaga
              </button>
              <button className="btn btn-primary" disabled={!file || sending} onClick={submit}>
                {sending ? "Yuborilmoqda..." : "To'ladim"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function OrdersTab({ api }) {
  const [orders, setOrders] = useState(null);

  useEffect(() => {
    api("/api/orders/mine")
      .then((d) => setOrders(d.orders))
      .catch(() => setOrders([]));
  }, [api]);

  if (!orders) return <div className="spinner" />;
  if (orders.length === 0) return <div className="card muted">Hali buyurtmalar yo'q.</div>;

  return (
    <>
      {orders.map((o) => (
        <div key={o.id} className="card">
          <div className="row">
            <div>
              <div style={{ fontWeight: 600 }}>{o.summary}</div>
              <div className="muted mono">{o.id}</div>
              {o.recipient && <div className="muted mono">Kimga: {o.recipient}</div>}
            </div>
            <div style={{ textAlign: "right" }}>
              <div className="mono">${o.amount_usd.toFixed(2)}</div>
              <StatusPill status={o.status} />
            </div>
          </div>
        </div>
      ))}
    </>
  );
}

function ReferralTab({ api, user }) {
  const [leaderboard, setLeaderboard] = useState(null);

  useEffect(() => {
    api("/api/leaderboard")
      .then((d) => setLeaderboard(d.leaderboard))
      .catch(() => setLeaderboard([]));
  }, [api]);

  if (!user) return null;

  const refLink = `https://t.me/${BOT_USERNAME}?start=ref_${user.user_id}`;

  return (
    <>
      <div className="card">
        <h3 style={{ marginBottom: 10 }} className="h-icon"><Icon name="users" size={18} />Referal dasturi</h3>
        <div className="grid-2" style={{ marginBottom: 12 }}>
          <div className="card" style={{ margin: 0, textAlign: "center" }}>
            <div className="muted">Taklif qilinganlar</div>
            <div style={{ fontSize: 22, fontWeight: 700 }}>{user.invited_count}</div>
          </div>
          <div className="card" style={{ margin: 0, textAlign: "center" }}>
            <div className="muted">Ishlab topilgan</div>
            <div className="mono" style={{ fontSize: 22, fontWeight: 700, color: "var(--gold)" }}>
              ${Number(user.earned).toFixed(2)}
            </div>
          </div>
        </div>
        <label>Sizning havolangiz</label>
        <input readOnly value={refLink} onClick={(e) => e.target.select()} />
        <button
          className="btn btn-primary"
          style={{ marginTop: 10 }}
          onClick={() => {
            navigator.clipboard?.writeText(refLink);
          }}
        >
          <IconLabel name="copy">Havolani nusxalash</IconLabel>
        </button>
      </div>

      <div className="card">
        <h3 style={{ marginBottom: 10 }} className="h-icon"><Icon name="trophy" size={18} />Reyting</h3>
        {!leaderboard && <div className="spinner" />}
        {leaderboard?.length === 0 && <div className="muted">Hozircha reyting bo'sh.</div>}
        {leaderboard?.map((u, i) => (
          <div key={i} className="row" style={{ marginBottom: 10 }}>
            <div className="row" style={{ gap: 10 }}>
              <Avatar photoUrl={u.photo_url} name={u.first_name} size={36} />
              <span>{u.first_name || u.username || "Foydalanuvchi"}</span>
            </div>
            <span className="mono" style={{ color: "var(--gold)" }}>
              ${Number(u.earned).toFixed(2)}
            </span>
          </div>
        ))}
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// BONUS — AdsGram rewarded reklama
// Bonusni frontend BERMAYDI: reklama tugagach AdsGram serveri bizning backend'ga xabar beradi,
// backend balansni oshiradi. Bu yerda faqat natijani kutib, balansni yangilaymiz.
// ---------------------------------------------------------------------------
function BonusTab({ api, setToast, refreshMe }) {
  const [status, setStatus] = useState(null);
  const [loadError, setLoadError] = useState(false);
  const [sdkReady, setSdkReady] = useState(false);
  const [adReady, setAdReady] = useState(false);
  const [watching, setWatching] = useState(false);
  const [now, setNow] = useState(() => Math.floor(Date.now() / 1000));
  const skew = useRef(0); // server va qurilma soati farqi
  const controller = useRef(null);
  const alive = useRef(true);

  const load = useCallback(async () => {
    try {
      const s = await api("/api/bonus/status");
      skew.current = s.server_time - Math.floor(Date.now() / 1000);
      setStatus(s);
      setLoadError(false);
      return s;
    } catch {
      setLoadError(true);
      return null;
    }
  }, [api]);

  useEffect(() => {
    alive.current = true;
    load();
    return () => {
      alive.current = false;
    };
  }, [load]);

  // Pauza hisoblagichi uchun sekundiga bir marta
  useEffect(() => {
    const t = setInterval(() => setNow(Math.floor(Date.now() / 1000)), 1000);
    return () => clearInterval(t);
  }, []);

  // AdsGram SDK faqat bonus yoqilgan bo'lsa yuklanadi
  useEffect(() => {
    if (!status?.enabled || !status.block_id) return;
    if (window.Adsgram) {
      setSdkReady(true);
      return;
    }
    let script = document.querySelector("script[data-adsgram]");
    if (!script) {
      script = document.createElement("script");
      script.src = "https://sad.adsgram.ai/js/sad.min.js";
      script.async = true;
      script.dataset.adsgram = "1";
      document.body.appendChild(script);
    }
    const onLoad = () => setSdkReady(true);
    const onError = () => setToast("Reklama moduli yuklanmadi. Internetni tekshirib, qayta oching.");
    script.addEventListener("load", onLoad);
    script.addEventListener("error", onError);
    return () => {
      script.removeEventListener("load", onLoad);
      script.removeEventListener("error", onError);
    };
  }, [status?.enabled, status?.block_id, setToast]);

  useEffect(() => {
    if (!sdkReady || !status?.enabled || !status.block_id || !window.Adsgram) return;
    try {
      controller.current = window.Adsgram.init({ blockId: String(status.block_id) });
      setAdReady(true);
    } catch {
      controller.current = null;
      setAdReady(false);
    }
  }, [sdkReady, status?.enabled, status?.block_id]);

  async function waitForReward(before) {
    for (let i = 0; i < 6; i++) {
      await new Promise((r) => setTimeout(r, i === 0 ? 1500 : 2500));
      if (!alive.current) return;
      const s = await load();
      if (s && s.used_today > before) {
        await refreshMe();
        setToast(`+$${fmtUsd(s.amount)} bonus balansingizga qo'shildi`);
        return;
      }
    }
    setToast("Bonus hali hisoblanmadi. Birozdan keyin balansingizni tekshiring.");
  }

  async function watch() {
    if (!controller.current || watching || !status) return;
    setWatching(true);
    const before = status.used_today;
    try {
      const result = await controller.current.show();
      if (result?.done) {
        setToast("Bonus hisoblanmoqda...");
        await waitForReward(before);
      }
    } catch (err) {
      // AdsGram: reklama topilmadi (error) yoki foydalanuvchi oxirigacha ko'rmadi
      setToast(
        err?.error
          ? "Hozircha reklama mavjud emas. Keyinroq urinib ko'ring."
          : "Reklama oxirigacha ko'rilmadi, shuning uchun bonus berilmaydi."
      );
    } finally {
      if (alive.current) setWatching(false);
    }
  }

  if (loadError && !status) {
    return (
      <div className="card">
        <p className="muted">Bonus ma'lumotini yuklab bo'lmadi.</p>
        <button className="btn btn-secondary" style={{ marginTop: 10 }} onClick={load}>
          Qayta urinish
        </button>
      </div>
    );
  }
  if (!status) return <div className="spinner" />;

  if (!status.enabled) {
    return (
      <div className="card">
        <h3 className="h-icon"><Icon name="gift" size={18} />Bonus</h3>
        <p className="muted" style={{ marginTop: 8 }}>
          Reklama ko'rib bonus olish hozircha mavjud emas.
        </p>
      </div>
    );
  }

  if (status.force_sub?.length > 0) {
    return (
      <div className="card">
        <h3 className="h-icon"><Icon name="gift" size={18} />Bonus</h3>
        <p className="muted" style={{ margin: "8px 0 12px" }}>
          Bonus olish uchun avval quyidagi kanallarga obuna bo'ling, so'ng bu bo'limni qayta oching.
        </p>
        {status.force_sub.map((c) => (
          <a key={c.url} href={c.url} target="_blank" rel="noreferrer" className="btn btn-secondary" style={{ display: "block", textAlign: "center", textDecoration: "none", marginBottom: 8 }}>
            <span className="btn-icon-label"><Icon name="megaphone" size={16} />{c.title}</span>
          </a>
        ))}
      </div>
    );
  }

  const cooldownLeft = Math.max(0, (status.next_available_at || 0) - (now + skew.current));
  const pct = status.daily_limit > 0 ? Math.min(100, (status.used_today / status.daily_limit) * 100) : 100;

  let label = <IconLabel name="play">Reklama ko'rish</IconLabel>;
  let disabled = false;
  if (watching) {
    label = "Reklama yuklanmoqda...";
    disabled = true;
  } else if (status.remaining <= 0) {
    label = "Bugungi limit tugadi";
    disabled = true;
  } else if (cooldownLeft > 0) {
    label = `Keyingisi: ${fmtCountdown(cooldownLeft)}`;
    disabled = true;
  } else if (!adReady) {
    label = "Yuklanmoqda...";
    disabled = true;
  }

  return (
    <>
      <div className="card">
        <h3 className="h-icon"><Icon name="gift" size={18} />Reklama ko'ring, bonus oling</h3>
        <p className="muted" style={{ marginTop: 8 }}>
          Har bir reklama uchun balansingizga{" "}
          <span className="mono" style={{ color: "var(--gold)", fontWeight: 600 }}>
            ${fmtUsd(status.amount)}
          </span>{" "}
          qo'shiladi. Reklamani oxirigacha ko'ring.
        </p>
        <div className="row" style={{ marginTop: 16 }}>
          <span className="muted">Bugun</span>
          <span className="mono">
            {status.used_today} / {status.daily_limit}
          </span>
        </div>
        <div className="progress" style={{ marginTop: 8 }}>
          <div style={{ width: `${pct}%` }} />
        </div>
        <button className="btn btn-primary" style={{ marginTop: 16 }} disabled={disabled} onClick={watch}>
          {label}
        </button>
        <p className="muted" style={{ marginTop: 10 }}>
          Bonus reklama tugagach bir necha soniya ichida balansga tushadi.
        </p>
      </div>
      <div className="card row">
        <span className="muted">Reklamadan jami topilgan</span>
        <span className="mono" style={{ color: "var(--gold)" }}>
          ${fmtUsd(status.total_earned)}
        </span>
      </div>
    </>
  );
}

// Konturli SVG ikonkalar (referens dizaynga mos: yupqa chiziq, currentColor)
function Icon({ name, size = 22 }) {
  const common = { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.7, strokeLinecap: "round", strokeLinejoin: "round" };
  const paths = {
    cart: <><circle cx="9" cy="20" r="1.4" /><circle cx="18" cy="20" r="1.4" /><path d="M2.5 3h2l2.2 11.2a2 2 0 0 0 2 1.6h7.8a2 2 0 0 0 2-1.6L21 7H6" /></>,
    gift: <><rect x="3.5" y="8.5" width="17" height="12" rx="1.5" /><path d="M3.5 12.5h17M12 8.5v12" /><path d="M12 8.5c-1-3-3-4-4.5-3S6 8.5 8 8.5h4Zm0 0c1-3 3-4 4.5-3S18 8.5 16 8.5h-4Z" /></>,
    wallet: <><rect x="3" y="6" width="18" height="13" rx="2" /><path d="M3 10h18" /><circle cx="16.5" cy="14" r="1" /></>,
    receipt: <><path d="M6 3h12v18l-2.5-1.5L13 21l-1-1.5L10 21l-2.5-1.5L6 21V3Z" /><path d="M9 8h6M9 12h6" /></>,
    users: <><circle cx="9" cy="8.5" r="3" /><path d="M3.5 19c.7-3 3-4.8 5.5-4.8s4.8 1.8 5.5 4.8" /><path d="M16 6.5a3 3 0 0 1 0 5.8M20.5 19c-.5-2.3-1.8-3.9-3.5-4.6" /></>,
    box: <><path d="M3.5 7.5 12 3l8.5 4.5L12 12 3.5 7.5Z" /><path d="M3.5 7.5V16l8.5 4.5V12" /><path d="M20.5 7.5V16L12 20.5" /></>,
    card: <><rect x="3" y="5.5" width="18" height="13" rx="2" /><path d="M3 9.5h18" /><path d="M6.5 14.5h4" /></>,
    settings: <><circle cx="12" cy="12" r="3" /><path d="M12 3v2.2M12 18.8V21M21 12h-2.2M5.2 12H3M18.1 5.9l-1.6 1.6M7.5 16.5l-1.6 1.6M18.1 18.1l-1.6-1.6M7.5 7.5 5.9 5.9" /></>,
    play: <><circle cx="12" cy="12" r="8.5" /><path d="M10 8.5v7l5.5-3.5L10 8.5Z" /></>,
    megaphone: <><path d="M3 10v4h3l6 3.5V6.5L6 10H3Z" /><path d="M16 9.5a3 3 0 0 1 0 5M19 7a6.5 6.5 0 0 1 0 10" /></>,
    key: <><circle cx="8" cy="14.5" r="3.2" /><path d="M10.2 12.3 17 5.5M15 7.5l2 2M17.5 5l1.8 1.8" /></>,
    star: <path d="m12 3 2.6 5.6 6.1.8-4.5 4.2 1.1 6-5.3-3-5.3 3 1.1-6-4.5-4.2 6.1-.8Z" />,
    gem: <><path d="M4 9 8 3h8l4 6-10 12L4 9Z" /><path d="M4 9h16M8 3l2 6-2 12M16 3l-2 6 2 12" /></>,
    check: <path d="M4 12.5 9.5 18 20 6" />,
    x: <path d="M6 6l12 12M18 6 6 18" />,
    ban: <><circle cx="12" cy="12" r="8.5" /><path d="M6.3 6.3l11.4 11.4" /></>,
    tool: <path d="M14.5 6.5a4 4 0 0 1-5 5L4 17l3 3 5.5-5.5a4 4 0 0 1 5-5L21 6l-3-3-3.5 3.5Z" />,
    mail: <><rect x="3" y="5.5" width="18" height="13" rx="2" /><path d="m3.5 6.5 8.5 7 8.5-7" /></>,
    trophy: <><path d="M7 4h10v6a5 5 0 0 1-10 0V4Z" /><path d="M7 6H4.5A2.5 2.5 0 0 0 5 11M17 6h2.5A2.5 2.5 0 0 1 19 11" /><path d="M12 15v3M9 21h6M9.5 21v-3h5v3" /></>,
    save: <><path d="M5 4h11l3 3v13H5V4Z" /><path d="M8 4v5h7V4M8 21v-7h8v7" /></>,
    eye: <><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z" /><circle cx="12" cy="12" r="2.6" /></>,
    "eye-off": <><path d="M3 3l18 18M10.6 6.1A9.7 9.7 0 0 1 12 6c6 0 9.5 6.5 9.5 6.5a15 15 0 0 1-3.3 4M6.4 7.4C4 9 2.5 12.5 2.5 12.5S6 19 12 19a10 10 0 0 0 3.6-.7" /><path d="M9.8 14.2a2.6 2.6 0 0 0 3.8-3.6" /></>,
    refresh: <><path d="M20 11a8 8 0 0 0-14.9-3.5M4 4v4.5H8.5" /><path d="M4 13a8 8 0 0 0 14.9 3.5M20 20v-4.5h-4.5" /></>,
    chart: <><path d="M4 20V10M11 20V4M18 20v-7" /><path d="M2.5 20.5h19" /></>,
    lock: <><rect x="4.5" y="10.5" width="15" height="10" rx="1.8" /><path d="M7.5 10.5V7a4.5 4.5 0 0 1 9 0v3.5" /></>,
    message: <><path d="M4 5h16v11H9l-4 4V5Z" /></>,
    copy: <><rect x="8.5" y="8.5" width="12" height="12" rx="1.8" /><path d="M15.5 8.5V5.5A1.8 1.8 0 0 0 13.7 3.7H5.3A1.8 1.8 0 0 0 3.5 5.5v8.4a1.8 1.8 0 0 0 1.8 1.8h3" /></>,
  };
  return <svg {...common}>{paths[name]}</svg>;
}

function IconLabel({ name, size = 16, children }) {
  return (
    <span className="btn-icon-label">
      <Icon name={name} size={size} />
      {children}
    </span>
  );
}

function TabBar({ tab, setTab }) {
  const items = [
    ["home", "cart", "Xarid"],
    ["bonus", "gift", "Bonus"],
    ["balance", "wallet", "Balans"],
    ["orders", "receipt", "Buyurtma"],
    ["referral", "users", "Referal"],
  ];
  return (
    <div className="tabbar">
      <div className="tabbar-inner">
        {items.map(([key, icon, label]) => (
          <button key={key} className={`tab-btn ${tab === key ? "active" : ""}`} onClick={() => setTab(key)}>
            <Icon name={icon} />
            <span>{label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function AdminApp() {
  const onUnauthorized = useCallback(() => {
    localStorage.removeItem(ADMIN_TOKEN_KEY);
    setAdmin(null);
  }, []);
  const api = useApi(ADMIN_TOKEN_KEY, { onUnauthorized });
  const [admin, setAdmin] = useState(null);
  const [checking, setChecking] = useState(true);
  const [tab, setTab] = useState("orders");
  const [toast, setToast] = useState("");

  useEffect(() => {
    async function verify() {
      const token = localStorage.getItem(ADMIN_TOKEN_KEY);
      if (!token) {
        setChecking(false);
        return;
      }
      try {
        const d = await api("/api/admin/verify");
        setAdmin(d);
      } catch {
        localStorage.removeItem(ADMIN_TOKEN_KEY);
      } finally {
        setChecking(false);
      }
    }
    verify();
  }, [api]);

  // Heartbeat — admin shu vaqtda Web App'da ekanini bildirish
  useEffect(() => {
    if (!admin) return;
    const beat = () => api("/api/admin/heartbeat", { method: "POST" }).catch(() => {});
    beat();
    const interval = setInterval(beat, 20000);
    const onUnload = () => api("/api/admin/leave", { method: "POST" }).catch(() => {});
    window.addEventListener("beforeunload", onUnload);
    return () => {
      clearInterval(interval);
      window.removeEventListener("beforeunload", onUnload);
      onUnload();
    };
  }, [admin, api]);

  if (checking) {
    return (
      <div className="app-shell">
        <div className="spinner" />
      </div>
    );
  }

  if (!admin) {
    return <AdminLogin api={api} onLogin={setAdmin} />;
  }

  return (
    <div className="app-shell">
      <Toast message={toast} onDone={() => setToast("")} />
      <div className="card row">
        <h2 className="h-icon"><Icon name="tool" size={20} />Admin panel</h2>
        <span className="muted">{admin.login}</span>
      </div>
      {admin.weak_password && (
        <div className="card" style={{ borderColor: "rgba(255, 107, 107, 0.45)" }}>
          <div style={{ fontWeight: 600, color: "var(--danger)" }}>Parolingiz zaif</div>
          <p className="muted" style={{ marginTop: 6 }}>
            Sozlamalar bo'limida parolni o'zgartiring: kamida 8 belgi va oddiy so'z bo'lmasin.
          </p>
          <button className="btn btn-secondary" style={{ marginTop: 10 }} onClick={() => setTab("settings")}>
            <IconLabel name="settings">Sozlamalarga o'tish</IconLabel>
          </button>
        </div>
      )}
      {tab === "orders" && <AdminOrders api={api} setToast={setToast} />}
      {tab === "payments" && <AdminPayments api={api} setToast={setToast} />}
      {tab === "users" && <AdminUsers api={api} setToast={setToast} />}
      {tab === "bonus" && <AdminBonus api={api} setToast={setToast} />}
      {tab === "settings" && (
        <>
          <AdminSettings api={api} setToast={setToast} />
          <AdminPassword api={api} setToast={setToast} onChanged={() => setAdmin((a) => ({ ...a, weak_password: false }))} />
        </>
      )}
      {tab === "broadcast" && <AdminBroadcast api={api} setToast={setToast} />}
      {tab === "admins" && admin.is_owner && <AdminAdmins api={api} setToast={setToast} />}
      <AdminTabBar tab={tab} setTab={setTab} isOwner={admin.is_owner} />
    </div>
  );
}

function AdminLogin({ api, onLogin }) {
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!login || !password || busy) return;
    setBusy(true);
    setError("");
    try {
      const d = await api("/api/admin/login", { method: "POST", body: { login, password } });
      localStorage.setItem(ADMIN_TOKEN_KEY, d.token);
      onLogin(d);
    } catch (e) {
      setError(e?.status === 429 ? errText(e) : "Login yoki parol noto'g'ri.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app-shell" style={{ display: "flex", alignItems: "center", minHeight: "100vh" }}>
      <div className="card" style={{ width: "100%" }}>
        <h2 style={{ marginBottom: 16, textAlign: "center", justifyContent: "center" }} className="h-icon"><Icon name="tool" size={20} />Admin kirish</h2>
        <label>Login</label>
        <input value={login} onChange={(e) => setLogin(e.target.value)} onKeyDown={(e) => e.key === "Enter" && submit()} />
        <label>Parol</label>
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} onKeyDown={(e) => e.key === "Enter" && submit()} />
        {error && <div style={{ color: "var(--danger)", marginTop: 10 }}>{error}</div>}
        <button className="btn btn-primary" style={{ marginTop: 18 }} disabled={busy} onClick={submit}>
          {busy ? "Tekshirilmoqda..." : "Kirish"}
        </button>
      </div>
    </div>
  );
}

function AdminTabBar({ tab, setTab, isOwner }) {
  const items = [
    ["orders", "box", "Buyurtma"],
    ["payments", "card", "To'lov"],
    ["users", "users", "Foyd."],
    ["bonus", "gift", "Bonus"],
    ["settings", "settings", "Sozlama"],
    ["broadcast", "megaphone", "Xabar"],
  ];
  if (isOwner) items.push(["admins", "key", "Admin"]);
  return (
    <div className="tabbar">
      <div className="tabbar-inner">
        {items.map(([key, icon, label]) => (
          <button key={key} className={`tab-btn ${tab === key ? "active" : ""}`} onClick={() => setTab(key)}>
            <Icon name={icon} size={20} />
            <span>{label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

// Foydalanuvchi yuklagan chekni admin panelda ko'rsatadi. Rasm server orqali (bot tokeni
// hech qachon brauzerga chiqmasdan) autentifikatsiyalangan so'rov bilan olinadi.
async function fetchAdminBlob(path) {
  const token = localStorage.getItem(ADMIN_TOKEN_KEY);
  const res = await fetch(`${API_URL}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) throw new Error("fetch_failed");
  return await res.blob();
}

function ReceiptViewer({ prId }) {
  const [url, setUrl] = useState(null);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);

  async function toggle() {
    if (url) {
      setOpen((o) => !o);
      return;
    }
    setLoading(true);
    setError(false);
    try {
      const blob = await fetchAdminBlob(`/api/admin/payments/${prId}/receipt`);
      setUrl(URL.createObjectURL(blob));
      setOpen(true);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ marginTop: 10 }}>
      <button className="btn btn-secondary" disabled={loading} onClick={toggle}>
        <IconLabel name={open ? "eye-off" : "eye"}>
          {loading ? "Yuklanmoqda..." : open ? "Chekni yashirish" : "Chekni ko'rish"}
        </IconLabel>
      </button>
      {error && <p style={{ color: "var(--danger)", fontSize: 12, marginTop: 6 }}>Chekni yuklab bo'lmadi, qayta urining.</p>}
      {open && url && (
        <img src={url} alt="To'lov cheki" style={{ width: "100%", borderRadius: 12, marginTop: 10, display: "block" }} />
      )}
    </div>
  );
}

function FilterBar({ filter, setFilter }) {
  return (
    <div className="card">
      <div className="grid-2">
        <button className={filter === "pending" ? "btn btn-primary" : "btn btn-secondary"} onClick={() => setFilter("pending")}>
          Kutilmoqda
        </button>
        <button className={filter === "all" ? "btn btn-primary" : "btn btn-secondary"} onClick={() => setFilter("all")}>
          Barchasi
        </button>
      </div>
    </div>
  );
}

function AdminOrders({ api, setToast }) {
  const [orders, setOrders] = useState(null);
  const [filter, setFilter] = useState("pending");
  const [busy, setBusy] = useState(null); // ayni paytda ishlanayotgan buyurtma ID

  const load = useCallback(() => {
    api(`/api/admin/orders?status=${filter === "all" ? "" : filter}`)
      .then((d) => setOrders(d.orders))
      .catch(() => setOrders([]));
  }, [api, filter]);

  useEffect(load, [load]);

  async function decide(id, decision) {
    if (busy) return;
    setBusy(id);
    try {
      await api(`/api/admin/orders/${encodeURIComponent(id)}/${decision}`, { method: "POST" });
      setToast(decision === "approve" ? "Tasdiqlandi" : "Bekor qilindi, pul qaytarildi");
    } catch (e) {
      setToast(`${errText(e)}`);
    } finally {
      setBusy(null);
      load();
    }
  }

  return (
    <>
      <FilterBar filter={filter} setFilter={setFilter} />
      {!orders && <div className="spinner" />}
      {orders?.length === 0 && <div className="card muted">Bo'sh.</div>}
      {orders?.map((o) => (
        <div key={o.id} className="card">
          <div className="row" style={{ gap: 10 }}>
            <div className="row" style={{ gap: 8 }}>
              <Avatar photoUrl={null} name={o.user_first_name} size={34} />
              <div>
                <div style={{ fontWeight: 600 }}>{o.user_first_name || "Foydalanuvchi"}</div>
                <div className="muted mono">{o.user_username ? `@${o.user_username}` : `ID: ${o.user_id}`}</div>
              </div>
            </div>
            <StatusPill status={o.status} />
          </div>
          <div className="info-list">
            <div className="info-row">
              <span className="muted">Buyurtma nomi</span>
              <span>{o.summary}</span>
            </div>
            <div className="info-row">
              <span className="muted">Kim buyurtma bermoqda</span>
              <span className="mono">{o.user_first_name || "—"}{o.user_username ? ` (@${o.user_username})` : ""}</span>
            </div>
            <div className="info-row">
              <span className="muted">Kimga</span>
              <span className="mono">{o.recipient || (o.user_username ? `@${o.user_username}` : "o'ziga")}</span>
            </div>
            <div className="info-row">
              <span className="muted">Foydalanuvchi ID</span>
              <span className="mono">{o.user_id}</span>
            </div>
            <div className="info-row">
              <span className="muted">Buyurtma ID</span>
              <span className="mono">{o.id}</span>
            </div>
            <div className="info-row">
              <span className="muted">Yaratilgan</span>
              <span className="mono">{new Date(o.created_at * 1000).toLocaleString()}</span>
            </div>
            <div className="info-row" style={{ borderTop: "1px solid var(--glass-border)", paddingTop: 8 }}>
              <span className="muted">Qancha to'layapti</span>
              <span className="mono" style={{ fontWeight: 700, color: "var(--gold)" }}>${o.amount_usd.toFixed(2)}</span>
            </div>
            <div className="info-row">
              <span className="muted">Joriy balansi</span>
              <span className="mono">${Number(o.user_balance ?? 0).toFixed(2)}</span>
            </div>
            {!!o.user_blocked && (
              <div className="info-row">
                <span className="muted">Holati</span>
                <span className="pill pill-rejected">Bloklangan</span>
              </div>
            )}
          </div>
          {o.status === "pending" && (
            <div className="grid-2" style={{ marginTop: 12 }}>
              <button className="btn btn-danger" disabled={busy === o.id} onClick={() => decide(o.id, "cancel")}>
                <IconLabel name="x">Bekor</IconLabel>
              </button>
              <button className="btn btn-primary" disabled={busy === o.id} onClick={() => decide(o.id, "approve")}>
                <IconLabel name="check">Tasdiqlash</IconLabel>
              </button>
            </div>
          )}
        </div>
      ))}
    </>
  );
}

function AdminPayments({ api, setToast }) {
  const [payments, setPayments] = useState(null);
  const [filter, setFilter] = useState("pending");
  const [amounts, setAmounts] = useState({});
  const [busy, setBusy] = useState(null);

  const load = useCallback(() => {
    api(`/api/admin/payments?status=${filter === "all" ? "" : filter}`)
      .then((d) => setPayments(d.payments))
      .catch(() => setPayments([]));
  }, [api, filter]);

  useEffect(load, [load]);

  async function act(pr, decision, body, okText) {
    if (busy) return;
    setBusy(pr.id);
    try {
      await api(`/api/admin/payments/${pr.id}/${decision}`, { method: "POST", body });
      setToast(okText);
    } catch (e) {
      setToast(`${errText(e)}`);
    } finally {
      setBusy(null);
      load();
    }
  }

  function approve(pr) {
    const amount = parseFloat(amounts[pr.id] ?? pr.amount_usd ?? 0);
    if (!amount || amount <= 0) {
      setToast("Summani kiriting");
      return;
    }
    act(pr, "approve", { amount_usd: amount }, "Tasdiqlandi, balans to'ldirildi");
  }

  function reject(pr) {
    act(pr, "reject", undefined, "Rad etildi");
  }

  function block(pr) {
    if (!window.confirm("Foydalanuvchini bloklaysizmi?")) return;
    act(pr, "block", undefined, "Foydalanuvchi bloklandi");
  }

  return (
    <>
      <FilterBar filter={filter} setFilter={setFilter} />
      {!payments && <div className="spinner" />}
      {payments?.length === 0 && <div className="card muted">Bo'sh.</div>}
      {payments?.map((pr) => (
        <div key={pr.id} className="card">
          <div className="row" style={{ gap: 10 }}>
            <div className="row" style={{ gap: 8 }}>
              <Avatar photoUrl={null} name={pr.user_first_name} size={34} />
              <div>
                <div style={{ fontWeight: 600 }}>{pr.user_first_name || "Foydalanuvchi"}</div>
                <div className="muted mono">{pr.user_username ? `@${pr.user_username}` : `ID: ${pr.user_id}`}</div>
              </div>
            </div>
            <StatusPill status={pr.status} />
          </div>
          <div className="info-list">
            <div className="info-row">
              <span className="muted">Order raqami</span>
              <span className="mono">#{pr.id}</span>
            </div>
            <div className="info-row">
              <span className="muted">Sanasi</span>
              <span className="mono">{new Date(pr.created_at * 1000).toLocaleString()}</span>
            </div>
            <div className="info-row">
              <span className="muted">Foydalanuvchi</span>
              <span className="mono">{pr.user_first_name || "—"}{pr.user_username ? ` (@${pr.user_username})` : ""}</span>
            </div>
            <div className="info-row">
              <span className="muted">Joriy balans</span>
              <span className="mono">${Number(pr.user_balance ?? 0).toFixed(2)}</span>
            </div>
            <div className="info-row" style={{ borderTop: "1px solid var(--glass-border)", paddingTop: 8 }}>
              <span className="muted">Qancha to'lov qilgani</span>
              <span className="mono" style={{ fontWeight: 700, color: "var(--gold)" }}>
                {pr.amount_usd ? `$${Number(pr.amount_usd).toFixed(2)}` : "ko'rsatilmagan"}
              </span>
            </div>
          </div>
          {pr.receipt_file_id ? (
            <ReceiptViewer prId={pr.id} />
          ) : (
            <p className="muted" style={{ marginTop: 8, fontSize: 12 }}>Chek rasmi biriktirilmagan.</p>
          )}
          {pr.status === "pending" && (
            <>
              <label>Tasdiqlanadigan summa (USD)</label>
              <input
                type="number"
                defaultValue={pr.amount_usd || ""}
                onChange={(e) => setAmounts((a) => ({ ...a, [pr.id]: e.target.value }))}
              />
              <div className="grid-2" style={{ marginTop: 10 }}>
                <button className="btn btn-danger" disabled={busy === pr.id} onClick={() => reject(pr)}>
                  <IconLabel name="x">Rad etish</IconLabel>
                </button>
                <button className="btn btn-primary" disabled={busy === pr.id} onClick={() => approve(pr)}>
                  <IconLabel name="check">Tasdiqlash</IconLabel>
                </button>
              </div>
              <button className="btn btn-secondary" style={{ marginTop: 8 }} disabled={busy === pr.id} onClick={() => block(pr)}>
                <IconLabel name="ban">Foydalanuvchini bloklash</IconLabel>
              </button>
            </>
          )}
        </div>
      ))}
    </>
  );
}

function AdminUsers({ api, setToast }) {
  const [users, setUsers] = useState(null);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState(null);

  const load = useCallback(() => {
    api(`/api/admin/users?search=${encodeURIComponent(search)}`)
      .then((d) => {
        setUsers(d.users);
        setTotal(d.total);
      })
      .catch(() => setUsers([]));
  }, [api, search]);

  // Har harfda emas, yozish to'xtagandan keyin so'raymiz
  useEffect(() => {
    const t = setTimeout(load, 300);
    return () => clearTimeout(t);
  }, [load]);

  return (
    <>
      <div className="card">
        <input placeholder="ID, username yoki ism bo'yicha qidirish" value={search} onChange={(e) => setSearch(e.target.value)} />
        <p className="muted" style={{ marginTop: 8 }}>Jami: {total}</p>
      </div>
      {!users && <div className="spinner" />}
      {users?.map((u) => (
        <div key={u.user_id} className="card row" style={{ cursor: "pointer" }} onClick={() => setSelected(u)}>
          <div className="row" style={{ gap: 10 }}>
            <Avatar photoUrl={u.photo_url} name={u.first_name} size={40} />
            <div>
              <div style={{ fontWeight: 600 }}>{u.first_name || "?"}</div>
              <div className="muted">{u.username ? `@${u.username}` : u.user_id}</div>
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div className="mono">${Number(u.balance).toFixed(2)}</div>
            {u.blocked ? <span className="pill pill-rejected">Bloklangan</span> : null}
          </div>
        </div>
      ))}
      {selected && (
        <UserDetailModal
          api={api}
          user={selected}
          onClose={() => setSelected(null)}
          onChanged={() => {
            setSelected(null);
            load();
          }}
          setToast={setToast}
        />
      )}
    </>
  );
}

function UserDetailModal({ api, user, onClose, onChanged, setToast }) {
  const [delta, setDelta] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  async function adjustBalance() {
    const d = parseFloat(delta);
    if (!d || busy) return;
    setBusy(true);
    try {
      await api(`/api/admin/users/${user.user_id}/adjust-balance`, { method: "POST", body: { delta: d } });
      setToast("Balans yangilandi");
      onChanged();
    } catch (e) {
      setToast(`${errText(e)}`);
    } finally {
      setBusy(false);
    }
  }

  async function toggleBlock() {
    if (busy) return;
    setBusy(true);
    try {
      await api(`/api/admin/users/${user.user_id}/block`, { method: "POST", body: { blocked: !user.blocked } });
      setToast(user.blocked ? "Blokdan chiqarildi" : "Bloklandi");
      onChanged();
    } catch (e) {
      setToast(`${errText(e)}`);
    } finally {
      setBusy(false);
    }
  }

  async function sendMessage() {
    if (!msg.trim() || busy) return;
    setBusy(true);
    try {
      await api(`/api/admin/users/${user.user_id}/message`, { method: "POST", body: { text: msg } });
      setToast("Xabar yuborildi");
      setMsg("");
    } catch (e) {
      setToast(`${errText(e)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-sheet" onClick={(e) => e.stopPropagation()}>
        <div className="row" style={{ marginBottom: 10 }}>
          <Avatar photoUrl={user.photo_url} name={user.first_name} />
          <div style={{ flex: 1, marginLeft: 10 }}>
            <div style={{ fontWeight: 700 }}>{user.first_name}</div>
            <div className="muted">{user.username ? `@${user.username} · ` : ""}ID: {user.user_id}</div>
          </div>
        </div>
        <div className="divider" />
        <div className="row">
          <span className="muted">Balans</span>
          <span className="mono">${Number(user.balance).toFixed(2)}</span>
        </div>
        <div className="row">
          <span className="muted">Taklif qilinganlar</span>
          <span>{user.invited_count}</span>
        </div>

        <label>Balansni o'zgartirish (+/- USD)</label>
        <input type="number" value={delta} onChange={(e) => setDelta(e.target.value)} placeholder="masalan: 5 yoki -5" />
        <button className="btn btn-primary" style={{ marginTop: 8 }} disabled={busy} onClick={adjustBalance}>
          Qo'llash
        </button>

        <label>Xabar yuborish</label>
        <textarea rows={3} value={msg} onChange={(e) => setMsg(e.target.value)} />
        <button className="btn btn-secondary" style={{ marginTop: 8 }} disabled={busy} onClick={sendMessage}>
          <IconLabel name="mail">Yuborish</IconLabel>
        </button>

        <button className={user.blocked ? "btn btn-primary" : "btn btn-danger"} style={{ marginTop: 14 }} disabled={busy} onClick={toggleBlock}>
          {user.blocked ? <IconLabel name="check">Blokdan chiqarish</IconLabel> : <IconLabel name="ban">Bloklash</IconLabel>}
        </button>

        <button className="btn btn-secondary" style={{ marginTop: 10 }} onClick={onClose}>
          Yopish
        </button>
      </div>
    </div>
  );
}

function AdminBonus({ api, setToast }) {
  const [data, setData] = useState(null);
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);
  const [showSecret, setShowSecret] = useState(false);
  const [regenBusy, setRegenBusy] = useState(false);

  const load = useCallback(() => {
    api("/api/admin/bonus")
      .then((d) => {
        setData(d);
        setForm(d.settings);
      })
      .catch(() => {});
  }, [api]);

  useEffect(load, [load]);

  if (!data || !form) return <div className="spinner" />;

  function update(key, value) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function save() {
    if (saving) return;
    setSaving(true);
    try {
      await api("/api/admin/bonus", {
        method: "POST",
        body: {
          enabled: !!form.enabled,
          amount: parseFloat(form.amount) || 0,
          daily_limit: parseInt(form.daily_limit) || 0,
          cooldown_sec: parseInt(form.cooldown_sec) || 0,
          daily_budget: parseFloat(form.daily_budget) || 0,
          block_id: String(form.block_id || "").trim(),
        },
      });
      setToast("Bonus sozlamalari saqlandi");
      load();
    } catch (e) {
      setToast(`${errText(e)}`);
    } finally {
      setSaving(false);
    }
  }

  async function regenerate() {
    if (regenBusy) return;
    if (!window.confirm("Maxfiy kalitni yangilaysizmi? AdsGram'dagi reward URL ham yangilanishi kerak bo'ladi.")) return;
    setRegenBusy(true);
    try {
      await api("/api/admin/bonus/regenerate-secret", { method: "POST" });
      setToast("Kalit yangilandi — AdsGram'da reward URL'ni yangilang");
      load();
    } catch (e) {
      setToast(`${errText(e)}`);
    } finally {
      setRegenBusy(false);
    }
  }

  function copy(text) {
    navigator.clipboard?.writeText(text);
    setToast("Nusxalandi");
  }

  const rewardUrl = `${API_URL}${data.reward_path}?userid=[userId]&secret=${data.secret}`;

  return (
    <>
      <div className="card">
        <h3 className="h-icon"><Icon name="gift" size={18} />Bonus (AdsGram reklama)</h3>
        <p className="muted" style={{ marginTop: 8 }}>
          Foydalanuvchilar Mini App'dagi "Bonus" bo'limida reklama ko'rib, balansga kichik summa qo'shib olishlari mumkin.
        </p>

        <div className="row" style={{ marginTop: 14 }}>
          <span className="muted">Yoqilgan</span>
          <input type="checkbox" style={{ width: "auto" }} checked={!!form.enabled} onChange={(e) => update("enabled", e.target.checked)} />
        </div>

        <label>AdsGram Block ID</label>
        <input value={form.block_id} onChange={(e) => update("block_id", e.target.value)} placeholder="masalan: 12345" />

        <label>Bitta reklama uchun bonus (USD)</label>
        <input type="number" step="0.0001" min="0" value={form.amount} onChange={(e) => update("amount", e.target.value)} />

        <label>Kuniga foydalanuvchiga nechta reklama</label>
        <input type="number" step="1" min="0" value={form.daily_limit} onChange={(e) => update("daily_limit", e.target.value)} />

        <label>Reklamalar orasidagi pauza (soniya)</label>
        <input type="number" step="1" min="0" value={form.cooldown_sec} onChange={(e) => update("cooldown_sec", e.target.value)} />

        <label>Kunlik jami byudjet (USD, 0 = cheksiz)</label>
        <input type="number" step="0.01" min="0" value={form.daily_budget} onChange={(e) => update("daily_budget", e.target.value)} />

        <button className="btn btn-primary" style={{ marginTop: 16 }} disabled={saving} onClick={save}>
          <IconLabel name="save">Saqlash</IconLabel>
        </button>
      </div>

      <div className="card">
        <h3 className="h-icon"><Icon name="settings" size={18} />AdsGram bilan ulash</h3>
        <p className="muted" style={{ marginTop: 8 }}>
          AdsGram dashboardida shu Block uchun <b>Reward postback URL</b> maydoniga quyidagi manzilni kiriting:
        </p>
        <div className="mono" style={{ background: "rgba(255,255,255,0.05)", borderRadius: 10, padding: 10, marginTop: 8, wordBreak: "break-all", fontSize: 12 }}>
          {showSecret ? rewardUrl : rewardUrl.replace(data.secret, "•".repeat(12))}
        </div>
        <div className="grid-2" style={{ marginTop: 10 }}>
          <button className="btn btn-secondary" onClick={() => setShowSecret((s) => !s)}>
            {showSecret ? <IconLabel name="eye-off">Yashirish</IconLabel> : <IconLabel name="eye">Ko'rsatish</IconLabel>}
          </button>
          <button className="btn btn-secondary" onClick={() => copy(rewardUrl)}>
            <IconLabel name="copy">Nusxalash</IconLabel>
          </button>
        </div>
        <button className="btn btn-danger" style={{ marginTop: 10 }} disabled={regenBusy} onClick={regenerate}>
          <IconLabel name="refresh">Kalitni yangilash</IconLabel>
        </button>
        <p className="muted" style={{ marginTop: 8 }}>
          Kalitni yangilasangiz, eski URL ishlamay qoladi — AdsGram'dagi manzilni ham darhol yangilang.
        </p>
      </div>

      <div className="card">
        <h3 className="h-icon"><Icon name="chart" size={18} />Statistika</h3>
        <div className="row" style={{ marginTop: 8 }}>
          <span className="muted">Bugun berilgan</span>
          <span className="mono">{data.stats.today_count} ta · ${data.stats.today_total.toFixed(4)}</span>
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          <span className="muted">Jami berilgan</span>
          <span className="mono">{data.stats.total_count} ta · ${data.stats.total_paid.toFixed(4)}</span>
        </div>
        {data.recent.length > 0 && (
          <>
            <div className="divider" />
            {data.recent.map((r) => (
              <div key={r.id} className="row" style={{ marginBottom: 8 }}>
                <span className="muted">
                  {r.first_name || (r.username ? `@${r.username}` : r.user_id)} ·{" "}
                  {new Date(r.created_at * 1000).toLocaleString()}
                </span>
                <span className="mono">${Number(r.amount_usd).toFixed(4)}</span>
              </div>
            ))}
          </>
        )}
      </div>
    </>
  );
}

function AdminSettings({ api, setToast }) {
  const [settings, setSettings] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api("/api/admin/pricing").then(setSettings).catch(() => {});
  }, [api]);

  if (!settings) return <div className="spinner" />;

  function update(key, value) {
    setSettings((s) => ({ ...s, [key]: value }));
  }

  async function save() {
    if (saving) return;
    setSaving(true);
    try {
      await api("/api/admin/pricing", { method: "POST", body: settings });
      setToast("Sozlamalar saqlandi");
    } catch (e) {
      setToast(`${errText(e)}`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card">
      <h3 className="h-icon"><Icon name="star" size={18} />Narxlar (USD)</h3>
      <label>1 dona Star narxi</label>
      <input type="number" step="0.001" value={settings.stars_price_per_unit} onChange={(e) => update("stars_price_per_unit", e.target.value)} />
      <label>Minimal Stars miqdori (dona)</label>
      <input type="number" step="1" value={settings.min_stars_quantity} onChange={(e) => update("min_stars_quantity", e.target.value)} />
      <label>Premium 3 oy</label>
      <input type="number" step="0.01" value={settings.premium_price_3m} onChange={(e) => update("premium_price_3m", e.target.value)} />
      <label>Premium 6 oy</label>
      <input type="number" step="0.01" value={settings.premium_price_6m} onChange={(e) => update("premium_price_6m", e.target.value)} />
      <label>Premium 9 oy</label>
      <input type="number" step="0.01" value={settings.premium_price_9m} onChange={(e) => update("premium_price_9m", e.target.value)} />
      <label>Premium 12 oy</label>
      <input type="number" step="0.01" value={settings.premium_price_12m} onChange={(e) => update("premium_price_12m", e.target.value)} />

      <div className="divider" />
      <h3>Balansni to'ldirish (karta)</h3>
      <label>1 USD = necha so'm</label>
      <input type="number" step="1" value={settings.usd_to_uzs_rate} onChange={(e) => update("usd_to_uzs_rate", e.target.value)} />
      <label>Karta raqami</label>
      <input value={settings.topup_card_number} onChange={(e) => update("topup_card_number", e.target.value)} placeholder="9860 1234 5678 9012" />
      <label>Karta egasi (F.I.Sh.)</label>
      <input value={settings.topup_card_holder} onChange={(e) => update("topup_card_holder", e.target.value)} placeholder="ALIYEV AZIZ" />

      <div className="divider" />
      <h3 className="h-icon"><Icon name="users" size={18} />Referal</h3>
      <label>Referal foizi (%)</label>
      <input type="number" step="0.1" value={settings.ref_percent} onChange={(e) => update("ref_percent", e.target.value)} />

      <div className="divider" />
      <h3 className="h-icon"><Icon name="message" size={18} />Matn</h3>
      <label>Xush kelibsiz matni</label>
      <textarea rows={3} value={settings.welcome_text} onChange={(e) => update("welcome_text", e.target.value)} />

      <div className="divider" />
      <h3 className="h-icon"><Icon name="lock" size={18} />Majburiy obuna</h3>
      <div className="row" style={{ marginTop: 8 }}>
        <span className="muted">Yoqilgan</span>
        <input
          type="checkbox"
          style={{ width: "auto" }}
          checked={settings.force_sub_enabled === "1"}
          onChange={(e) => update("force_sub_enabled", e.target.checked ? "1" : "0")}
        />
      </div>
      <p className="muted">Kanallar botda boshqariladi: /channels, /addchannel, /delchannel buyruqlari.</p>

      <button className="btn btn-primary" style={{ marginTop: 16 }} disabled={saving} onClick={save}>
        <IconLabel name="save">Saqlash</IconLabel>
      </button>
    </div>
  );
}

function AdminPassword({ api, setToast, onChanged }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!current || !next || busy) return;
    setBusy(true);
    try {
      await api("/api/admin/change-password", { method: "POST", body: { current_password: current, new_password: next } });
      setToast("Parol yangilandi");
      setCurrent("");
      setNext("");
      onChanged?.();
    } catch (e) {
      setToast(`${errText(e)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <h3 className="h-icon"><Icon name="key" size={18} />Parolni o'zgartirish</h3>
      <label>Joriy parol</label>
      <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} />
      <label>Yangi parol (kamida 8 belgi)</label>
      <input type="password" value={next} onChange={(e) => setNext(e.target.value)} />
      <button className="btn btn-primary" style={{ marginTop: 12 }} disabled={busy} onClick={submit}>
        Yangilash
      </button>
    </div>
  );
}

function AdminBroadcast({ api, setToast }) {
  const [text, setText] = useState("");
  const [state, setState] = useState(null);
  const timer = useRef(null);
  const alive = useRef(true);

  const poll = useCallback(async () => {
    try {
      const s = await api("/api/admin/broadcast/status");
      if (!alive.current) return;
      setState(s);
      if (s.running) timer.current = setTimeout(poll, 2000);
    } catch {
      /* jim */
    }
  }, [api]);

  useEffect(() => {
    alive.current = true;
    poll();
    return () => {
      alive.current = false;
      clearTimeout(timer.current);
    };
  }, [poll]);

  async function send() {
    if (!text.trim()) return;
    try {
      await api("/api/admin/broadcast", { method: "POST", body: { text } });
      setToast("Yuborish boshlandi");
      setText("");
      clearTimeout(timer.current);
      poll();
    } catch (e) {
      setToast(`${errText(e)}`);
    }
  }

  const running = !!state?.running;
  const done = state ? state.sent + state.failed : 0;
  const pct = state && state.total > 0 ? Math.min(100, (done / state.total) * 100) : 0;

  return (
    <div className="card">
      <h3 className="h-icon"><Icon name="megaphone" size={18} />Barchaga xabar yuborish</h3>
      <label>Xabar matni</label>
      <textarea rows={5} value={text} onChange={(e) => setText(e.target.value)} />
      <button className="btn btn-primary" style={{ marginTop: 12 }} disabled={running || !text.trim()} onClick={send}>
        {running ? "Yuborilmoqda..." : "Yuborish"}
      </button>
      {running && (
        <div style={{ marginTop: 14 }}>
          <div className="row">
            <span className="muted">Yuborilmoqda</span>
            <span className="mono">
              {done} / {state.total}
            </span>
          </div>
          <div className="progress" style={{ marginTop: 8 }}>
            <div style={{ width: `${pct}%` }} />
          </div>
        </div>
      )}
      {state && !running && state.finished_at > 0 && (
        <p className="muted" style={{ marginTop: 12 }}>
          Oxirgi yuborish: yuborildi {state.sent}, xato {state.failed}
        </p>
      )}
    </div>
  );
}

function AdminAdmins({ api, setToast }) {
  const [admins, setAdmins] = useState(null);
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api("/api/admin/admins")
      .then((d) => setAdmins(d.admins))
      .catch(() => setAdmins([]));
  }, [api]);

  useEffect(load, [load]);

  async function add() {
    if (!login || !password || busy) return;
    setBusy(true);
    try {
      await api("/api/admin/admins", { method: "POST", body: { login, password } });
      setToast("Admin qo'shildi");
      setLogin("");
      setPassword("");
      load();
    } catch (e) {
      setToast(`${errText(e)}`);
    } finally {
      setBusy(false);
    }
  }

  async function remove(l) {
    if (!window.confirm(`"${l}" adminni o'chirasizmi?`)) return;
    try {
      await api(`/api/admin/admins/${encodeURIComponent(l)}`, { method: "DELETE" });
      setToast("Admin o'chirildi");
      load();
    } catch (e) {
      setToast(`${errText(e)}`);
    }
  }

  return (
    <>
      <div className="card">
        <h3 className="h-icon"><Icon name="key" size={18} />Yangi admin qo'shish</h3>
        <label>Login</label>
        <input value={login} onChange={(e) => setLogin(e.target.value)} />
        <label>Parol (kamida 8 belgi)</label>
        <input value={password} onChange={(e) => setPassword(e.target.value)} />
        <button className="btn btn-primary" style={{ marginTop: 12 }} disabled={busy} onClick={add}>
          Qo'shish
        </button>
      </div>
      {admins?.map((a) => (
        <div key={a.login} className="card row">
          <div>
            <div style={{ fontWeight: 600 }}>{a.login}</div>
            {a.is_owner ? <span className="pill pill-approved">Bosh admin</span> : <span className="muted">Admin</span>}
          </div>
          {!a.is_owner && (
            <button className="btn btn-danger" style={{ width: "auto", padding: "8px 14px" }} onClick={() => remove(a.login)}>
              O'chirish
            </button>
          )}
        </div>
      ))}
    </>
  );
}

