# Smart Farm AI — Project Handover Summary

**Role:** Member 1 — Frontend & UI/UX Engineering  
**Project:** Smart Farm AI (Jordan Valley Open-Field Tomato Assistant)  
**Scope:** Two-day Academic Demo  
**Date of Handover:** October 10, 2026  

---

## 1. Project Objective

The goal of this project is to build an intelligent decision-support web application for open-field tomato farmers in the Jordan Valley (غور الأردن), Jordan. The application provides:
1. A **cinematic, high-aesthetic agricultural dashboard** reflecting farm metrics, irrigation calculations, financial breakdowns, and crop health.
2. A **conversational agricultural AI assistant** and a dedicated **dynamic recommendations engine** that generates personalized guidance based on individual farm conditions (stage, moisture, heat, cost).
3. A **natural Jordanian Arabic Voice interface** utilizing **Microsoft Azure AI Speech** (`ar-JO-TaimNeural`) to audibly advise farmers in their native dialect and phrasing.

As Member 1 of a three-person team, the responsibility is strictly frontend architecture, design fidelity, user experience, mock data modeling, and backend API integration readiness. The landing page branding and layout are preserved, and backend schemas/servers are decoupled.

---

## 2. Technology Stack & Tools Used

* **Core Stack:** Pure HTML5, Vanilla JavaScript (ES6+ Modules/IIFE), and Vanilla CSS3.
* **Architecture Pattern:** Zero-build, vanilla architecture (no React/Node bundler required, loads instantly in browser via any static server or file host).
* **Styling & Aesthetics:** Deep forest green glassmorphism (`backdrop-filter: blur`), CSS custom properties (variables), modern typography (`Outfit` & `Cairo` Google Fonts), and responsive flex/grid layouts.
* **Internationalization:** Complete client-side bilingual system (Arabic `ar` with native RTL, and English `en` with LTR).
* **Testing & Inspection Tools:**
  * Local Python HTTP server (`http://localhost:5500`)
  * Browser Subagent automated end-to-end testing, responsive viewport checks (desktop 1440x900, tablet 768px, mobile 390x844), and interactive event verification.
  * Node.js script runners for unit testing text normalization rules.

---

## 3. What Has Been Completed

### Phase 1: Reference Dashboard Design & Visual Aesthetics
* Implemented [`dashboard.html`](file:///d:/htu/dashboard.html) and [`css/dashboard.css`](file:///d:/htu/css/dashboard.css) reproducing the cinematic agricultural glassmorphism UI.
* Created botanical visual representations, dark forest green palette, atmospheric lighting, and clean KPI badges.
* Integrated complete SVG sprite system with bespoke icons for soil moisture, evapotranspiration, temperature, irrigation, financial status, and audio playback.

### Phase 2: Dynamic Farm Data & Calculation Integration
* Built [`js/types.js`](file:///d:/htu/js/types.js) establishing JSDoc schemas for farms, calculation results, financial line items, weather, and recommendations.
* Created [`js/mock-data.js`](file:///d:/htu/js/mock-data.js) providing 3 realistic Jordan Valley tomato farms:
  * **Farm 1 (Karameh):** Flowering stage, drip irrigation, complete data.
  * **Farm 2 (Deir Alla):** Fruiting stage, furrow irrigation, elevated water deficit, missing inspection data.
  * **Farm 3 (South Shuna):** Vegetative stage, drip irrigation, cost overruns, partial calculation results.
* Built dynamic switching logic in [`js/app.js`](file:///d:/htu/js/app.js): KPI cards, summary grids, irrigation charts, weather widgets, and financial cards update dynamically based on the selected farm.
* Distinctly separated **recorded costs vs. projected costs** and **actual revenue vs. projected revenue**.
* Missing data displays informative fallback states rather than invented or zero values.

### Phase 3: Personalized Recommendations Engine
* Created [`js/demo-recommendations.js`](file:///d:/htu/js/demo-recommendations.js) generating multi-dimensional recommendations tailored to farm parameters (irrigation deficits, flowering heat stress, fertilizer split, harvest readiness).
* Built [`js/recommendation-card.js`](file:///d:/htu/js/recommendation-card.js): A reusable component that formats recommendations with:
  * Short situation summary
  * Suggested action
  * Rationale ("Why")
  * Missing information / limitations
  * Supporting agronomic evidence and sources
* Integrated the recommendation modal (`#dlg-recs`) accessible via the AI assistant panel and top navigation.

### Phase 4: Natural Jordanian Arabic Voice System
* **Provider:** Microsoft Azure AI Speech (`ar-JO-TaimNeural`, locale `ar-JO`).
* **Text Normalizer ([`js/speech-text.js`](file:///d:/htu/js/speech-text.js)):**
  * Converts numbers, percentages, temperatures, dates, and Jordanian Dinars (`JOD`) into spoken Arabic words.
  * Example: `JOD 800` → `"ثمانمئة دينار أردني"`, `32°C` → `"اثنتان وثلاثون درجة مئوية"`, `2026-10-10` → `"العاشر من تشرين الأول عام ألفين وستة وعشرين"`.
* **Voice Player Component ([`js/voice.js`](file:///d:/htu/js/voice.js)):**
  * Audio controls: Play, pause, stop, replay, progress scrub bar, and time indicators.
  * Error handling: When backend Azure service is unavailable, presents an explanatory Arabic error with a Retry button.
  * Accessible fallback: Optional secondary browser SpeechSynthesis button (explicitly labeled as lower quality, never default).
  * Authoritative transcript preview block.
* **API Isolation ([`js/api.js`](file:///d:/htu/js/api.js)):**
  * Added `requestVoice()` calling `POST /assistant/voice`.
  * Verifies `voice_id === 'ar-JO-TaimNeural'` (rejects mismatched voices with `VOICE_MISMATCH`).
  * Enforces credential security: Azure keys never touch client code.
* **Backend Contract ([`docs/voice-backend-contract.md`](file:///d:/htu/docs/voice-backend-contract.md)):** Documented exact FastAPI request/response schema, error codes, environment variables, and sample Python Azure SDK implementation for Member 2.

---

## 4. Work Completed vs. Planned / Pending Work

| Feature Area | Completed in Frontend (Member 1) | Pending / Responsibility of Member 2 & 3 |
| :--- | :--- | :--- |
| **Landing Page** | Preserved branding & "Get Started" navigation | Production hosting & domain mapping |
| **Dashboard UI** | Glassmorphism, responsive layout, RTL/LTR bilingual toggle | Live-provider verification and complete real farm ingestion |
| **Farm Selection** | Dynamic client switcher, mock data for 3 farms, graceful null states | Profile fields beyond the current farm CRUD contract |
| **Calculations** | ET0 irrigation estimates when inputs are complete; actual expense and sale-derived finance metrics; dated supplier fertilizer listings and one-package budget comparison | Biological yield prediction, official current item-level fertilizer prices, and water-budget scenario UI |
| **AI Recommendations** | Dynamic cards, modal, evidence display, and demo generator; live API returns profile-completeness reminders | Reviewed agronomic knowledge/RAG and source-backed agronomic recommendations |
| **Voice Interface** | UI player, text normalizer, error states; backend Azure Speech REST contract is implemented | Valid Azure credentials and end-to-end audio verification |
| **Chat Assistant** | Chat UI and demo responses; backend Groq call with a bilingual fallback | Valid Groq credentials, curated tomato knowledge base, and source citations |
| **Reporting** | Personalized bilingual PDF export is available from the dashboard | Browser-generated PDF; see current frontend implementation |

---

## 5. Technical Decisions & Architectural Rules

1. **Vanilla Stack Preservation:** The codebase deliberately avoids React, Node bundlers, or heavy UI frameworks to allow instant, dependency-free execution in any academic evaluation environment.
2. **Zero Client-Side Secrets:** Azure Speech keys (`AZURE_SPEECH_KEY`) and OpenAI/LLM keys must **never** be configured in frontend code. The frontend only consumes endpoints via `SFA_API`.
3. **No Fake Playback:** When Azure Speech audio is unavailable, the UI **never** fakes audio playback using timer progress bars. It displays a genuine error status with retry options.
4. **Authoritative Transcript Alignment:** While the frontend normalizes Arabic for preview purposes, the final transcript matches the backend `text` field returned with the audio file.
5. **Data Origin Transparency:** All demo data is explicitly labeled with badge `[تجريبي / Demo]` to avoid misleading users during academic evaluation.

---

## 6. Problems Encountered and Solutions

* **Problem 1: Frontend Stack Ambiguity**
  * *Context:* Initial requests referenced React components and dependencies, but inspecting the directory revealed pure HTML/CSS/JS without `package.json`.
  * *Solution:* Maintained strict alignment with the existing vanilla architecture, structuring modular components under the `window.SFA_*` namespace.
* **Problem 2: Number & Date Pronunciation in Arabic Speech**
  * *Context:* Raw TTS engines frequently mispronounce digits, abbreviations (`JOD`, `mm`, `°C`), and ISO dates (`2026-10-10`) or read them in English.
  * *Solution:* Built `speech-text.js` to normalize numbers according to classical Arabic grammar rules (counting masculine/feminine nouns, dual forms for 2, plural forms for 3-10, and genitive forms for dates).
* **Problem 3: Azure Audio Validation Without Active Backend Keys**
  * *Context:* Running in an offline/mock frontend environment meant actual synthesized audio could not be generated.
  * *Solution:* Implemented robust mock/error handling flows. Verified the UI states (loading spinner, error messaging, transcript, retry, and optional browser fallback) in the browser subagent, while providing full disclosure that live sound has not yet been heard live.

---

## 7. Instructions for the Next AI / Developer

To continue work seamlessly:
1. **Server Execution:** Run `python -m http.server 5500` inside `d:\htu` and open `http://localhost:5500/dashboard.html`.
2. **Backend Connection:** Start the API and open `dashboard.html?api=http%3A%2F%2Flocalhost%3A8000%2Fapi`. The query parameter selects live mode; without it, the frontend retains its labeled mock-data mode. See `docs/backend-setup.md` for setup details.
3. **Voice Testing with Azure:** Set `AZURE_SPEECH_KEY` and `AZURE_SPEECH_REGION` in the server `.env`, start the API, then request speech for an available recommendation. The local tests use mocked provider audio; confirm real Azure synthesis before presenting it as live.
4. **Next Feature Priority:**
   * Add reviewed tomato guidance and citations before enabling agronomic AI recommendations or source-backed chat answers.
   * Refresh the dated supplier fertilizer snapshot from verified listings; connect current official Department of Statistics item-level fertilizer values if a supported dataset/API becomes available. Also test live Open-Meteo, Groq, Azure Speech, and PostgreSQL integrations with configured credentials/services.
