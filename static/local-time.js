// Finds every element with a data-utc attribute (a raw UTC timestamp in
// ISO 8601 format, e.g. "2026-07-26T05:30:00+00:00") and fills it in with
// that time formatted in whichever timezone the visiting browser is
// actually in — automatically, no server-side timezone config needed.
//
// Usage in a template:
//   <span class="local-time" data-utc="{{ row.created_at }}"></span>
// Add data-date-only="true" for displays that only ever showed a date,
// not a time (e.g. a "trial expiry date" column).
//
// Falls back to leaving the raw value visible if the browser can't parse
// it (e.g. it was empty/null), so a formatting failure never hides data.
(function () {
  function formatLocalTime(utcString, dateOnly) {
    // Every timestamp in this app is stored as UTC, but some are passed
    // through without an explicit "Z"/offset marker (e.g. a raw Python
    // datetime's .isoformat() called directly in a template). Without a
    // marker, JavaScript's Date parser treats the string as browser-local
    // time instead of UTC — so if there's no "Z" or "+HH:MM"/"-HH:MM"
    // offset already present, assume UTC and add one.
    const hasTimezoneMarker = /(Z|[+-]\d{2}:?\d{2})$/.test(utcString);
    const normalized = hasTimezoneMarker ? utcString : utcString + "Z";

    const date = new Date(normalized);

    if (isNaN(date.getTime())) {
      return utcString;
    }

    const options = {
      day: "numeric",
      month: "short",
      year: "numeric",
    };

    if (!dateOnly) {
      options.hour = "numeric";
      options.minute = "2-digit";
      options.hour12 = true;
    }

    return date.toLocaleString(undefined, options);
  }

  function applyLocalTimes() {
    document.querySelectorAll(".local-time[data-utc]").forEach(function (el) {
      const utcString = el.getAttribute("data-utc");

      if (!utcString || utcString === "None") {
        return;
      }

      const dateOnly = el.getAttribute("data-date-only") === "true";

      el.textContent = formatLocalTime(utcString, dateOnly);
    });
  }

  // Exposed globally so pages that replace rows via AJAX (e.g. the
  // dashboard's auto-refresh) can re-run formatting on newly-inserted
  // elements without a full page reload.
  window.applyLocalTimes = applyLocalTimes;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", applyLocalTimes);
  } else {
    applyLocalTimes();
  }
})();
