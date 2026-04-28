Use this flow:
Browser UI -> Your UI backend (BFF) -> Solvetax API
Browser never sees PUBLIC_API_KEY.
1) Frontend (UI) change
Instead of calling Solvetax directly, call your own BFF endpoint.
Example:
UI currently: POST https://api.solvetax.com/api/v1/customers ❌
UI new: POST https://your-ui-backend.com/public/customers ✅
Same for income tax:
POST /public/income-tax on BFF.
2) BFF env
On BFF server add:
SOLVETAX_BASE_URL=https://<your-solvetax-host>
SOLVETAX_PUBLIC_API_KEY=<same PUBLIC_API_KEY value>
3) BFF route example (Node/Express)
import express from "express";
import axios from "axios";
const app = express();
app.use(express.json());
const BASE_URL = process.env.SOLVETAX_BASE_URL;
const PUBLIC_KEY = process.env.SOLVETAX_PUBLIC_API_KEY;
app.post("/public/customers", async (req, res) => {
  try {
    const r = await axios.post(`${BASE_URL}/api/v1/customers`, req.body, {
      headers: {
        "Content-Type": "application/json",
        "X-Public-Api-Key": PUBLIC_KEY,
      },
      timeout: 10000,
    });
    res.status(r.status).json(r.data);
  } catch (e) {
    const status = e.response?.status || 500;
    const data = e.response?.data || { detail: "Upstream error" };
    res.status(status).json(data);
  }
});
app.post("/public/income-tax", async (req, res) => {
  try {
    const r = await axios.post(`${BASE_URL}/api/v1/income-tax`, req.body, {
      headers: {
        "Content-Type": "application/json",
        "X-Public-Api-Key": PUBLIC_KEY,
      },
      timeout: 10000,
    });
    res.status(r.status).json(r.data);
  } catch (e) {
    const status = e.response?.status || 500;
    const data = e.response?.data || { detail: "Upstream error" };
    res.status(status).json(data);
  }
});
4) UI call example (React/fetch)
await fetch("/public/customers", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(payload),
});
No X-Public-Api-Key in browser code.
5) Why this is better
Key stays only on server.
Users cannot inspect and steal it from browser bundle/network.
You can add extra protections in BFF (IP checks, captcha, bot checks, logging).
If you tell me your UI stack (Next.js, React+Node, Django, etc.), I can give exact ready-to-paste BFF files.