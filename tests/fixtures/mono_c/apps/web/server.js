const express = require("express");
const app = express();
app.get("/health", (req, res) => res.send("ok"));
app.listen(process.env.PORT || 3000);
const fs = require("fs");
fs.writeFileSync("/tmp/cache.json", "{}");
