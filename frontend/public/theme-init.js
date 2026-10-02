// Apply the saved theme before first paint (no flash). External file so the
// Content-Security-Policy can forbid inline scripts. Theme is not sensitive data.
try {
  var t = localStorage.getItem("adapt.theme");
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
} catch (e) {}
