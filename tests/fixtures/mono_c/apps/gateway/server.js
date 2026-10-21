const express = require("express");
const app = express();
app.get("/health", (req, res) => res.send("ok"));
app.listen(process.env.PORT || 3000);
const BILLING = process.env.BILLING_URL;
const USERS = process.env["USERS_URL"];
