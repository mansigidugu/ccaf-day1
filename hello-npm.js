(async () => {
  const res = await fetch("https://example.com");
  const text = await res.text();
  console.log("Status:", res.status);
  console.log(text.slice(0, 200));
})();
