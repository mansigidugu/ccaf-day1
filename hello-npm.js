const url = "https://example.com";

const res = await fetch(url);

const text = await res.text();

console.log("Status:", res.status);

console.log(text.slice(0,200));