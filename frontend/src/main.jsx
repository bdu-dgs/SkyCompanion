import React, { lazy, Suspense } from "react";
import ReactDOM from "react-dom/client";
import "./index.css";

const Page = /^\/live\/?$/.test(window.location.pathname)
  ? lazy(() => import("./LiveMonitor.jsx"))
  : lazy(() => import("./App.jsx"));

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <Suspense fallback={<p style={{ padding: "2rem" }}>Opening SkyCompanion...</p>}>
      <Page />
    </Suspense>
  </React.StrictMode>
);
