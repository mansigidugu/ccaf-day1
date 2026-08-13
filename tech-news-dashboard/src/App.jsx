import { useEffect, useMemo, useState } from "react";

const fallbackNews = [
  {
    id: 1,
    title: "AI Models Continue to Transform Software Development",
    source: "Tech News",
    category: "AI",
    time: "2 hours ago",
    readingTime: "4 min read",
    url: "https://news.ycombinator.com/",
    thumbnail: "https://picsum.photos/seed/ai1/500/300",
  },
  {
    id: 2,
    title: "Open Source Tools Gain Popularity Among Developers",
    source: "Hacker News",
    category: "Programming",
    time: "3 hours ago",
    readingTime: "5 min read",
    url: "https://news.ycombinator.com/",
    thumbnail: "https://picsum.photos/seed/code1/500/300",
  },
  {
    id: 3,
    title: "Cloud Infrastructure Continues Rapid Growth",
    source: "Tech News",
    category: "Cloud",
    time: "5 hours ago",
    readingTime: "3 min read",
    url: "https://news.ycombinator.com/",
    thumbnail: "https://picsum.photos/seed/cloud1/500/300",
  },
  {
    id: 4,
    title: "Cybersecurity Teams Adopt More AI Automation",
    source: "Security News",
    category: "Cybersecurity",
    time: "6 hours ago",
    readingTime: "6 min read",
    url: "https://news.ycombinator.com/",
    thumbnail: "https://picsum.photos/seed/security1/500/300",
  },
  {
    id: 5,
    title: "Startup Funding Shows New Momentum in Technology",
    source: "Startup News",
    category: "Startups",
    time: "8 hours ago",
    readingTime: "4 min read",
    url: "https://news.ycombinator.com/",
    thumbnail: "https://picsum.photos/seed/startup1/500/300",
  },
  {
    id: 6,
    title: "Modern Web Development Tools Continue to Improve",
    source: "Developer News",
    category: "Web Dev",
    time: "9 hours ago",
    readingTime: "5 min read",
    url: "https://news.ycombinator.com/",
    thumbnail: "https://picsum.photos/seed/web1/500/300",
  },
  {
    id: 7,
    title: "Mobile Development Trends Developers Should Watch",
    source: "Mobile News",
    category: "Mobile",
    time: "10 hours ago",
    readingTime: "3 min read",
    url: "https://news.ycombinator.com/",
    thumbnail: "https://picsum.photos/seed/mobile1/500/300",
  },
];

const githubRepos = [
  {
    id: "repo1",
    name: "facebook/react",
    stars: "238k",
    language: "JavaScript",
    description: "A JavaScript library for building user interfaces.",
    growth: "+420 today",
    category: "Programming",
    url: "https://github.com/facebook/react",
  },
  {
    id: "repo2",
    name: "vercel/next.js",
    stars: "135k",
    language: "JavaScript",
    description: "The React framework for the web.",
    growth: "+310 today",
    category: "Web Dev",
    url: "https://github.com/vercel/next.js",
  },
  {
    id: "repo3",
    name: "pytorch/pytorch",
    stars: "95k",
    language: "Python",
    description: "Deep learning framework for AI applications.",
    growth: "+260 today",
    category: "AI",
    url: "https://github.com/pytorch/pytorch",
  },
  {
    id: "repo4",
    name: "kubernetes/kubernetes",
    stars: "120k",
    language: "Go",
    description: "Production-grade container orchestration.",
    growth: "+190 today",
    category: "Cloud",
    url: "https://github.com/kubernetes/kubernetes",
  },
];

const categories = [
  "All",
  "AI",
  "Programming",
  "Startups",
  "Cybersecurity",
  "Cloud",
  "Mobile",
  "Web Dev",
];

function App() {
  const [news, setNews] = useState([]);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("All");

  const [darkMode, setDarkMode] = useState(() => {
    return localStorage.getItem("newsDarkMode") === "true";
  });

  const [bookmarks, setBookmarks] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem("newsBookmarks")) || [];
    } catch {
      return [];
    }
  });

  const [loading, setLoading] = useState(true);
  const [visibleCount, setVisibleCount] = useState(6);
  const [lastUpdated, setLastUpdated] = useState(new Date());

  function assignCategory(title = "") {
    const text = title.toLowerCase();

    if (
      text.includes("ai") ||
      text.includes("model") ||
      text.includes("llm") ||
      text.includes("machine learning")
    ) {
      return "AI";
    }

    if (
      text.includes("security") ||
      text.includes("hack") ||
      text.includes("malware")
    ) {
      return "Cybersecurity";
    }

    if (
      text.includes("cloud") ||
      text.includes("aws") ||
      text.includes("kubernetes")
    ) {
      return "Cloud";
    }

    if (
      text.includes("startup") ||
      text.includes("funding")
    ) {
      return "Startups";
    }

    if (
      text.includes("mobile") ||
      text.includes("android") ||
      text.includes("iphone")
    ) {
      return "Mobile";
    }

    if (
      text.includes("web") ||
      text.includes("browser") ||
      text.includes("javascript")
    ) {
      return "Web Dev";
    }

    return "Programming";
  }

  function formatTime(timestamp) {
    if (!timestamp) {
      return "Recently";
    }

    const seconds = Math.floor(Date.now() / 1000) - timestamp;
    const hours = Math.floor(seconds / 3600);

    if (hours < 1) return "Less than 1 hour ago";
    if (hours === 1) return "1 hour ago";
    if (hours < 24) return `${hours} hours ago`;

    return `${Math.floor(hours / 24)} days ago`;
  }

  async function loadNews() {
    setLoading(true);

    try {
      const response = await fetch(
        "https://hacker-news.firebaseio.com/v0/topstories.json"
      );

      const ids = await response.json();

      const stories = await Promise.all(
        ids.slice(0, 30).map(async (id) => {
          const storyResponse = await fetch(
            `https://hacker-news.firebaseio.com/v0/item/${id}.json`
          );

          return storyResponse.json();
        })
      );

      const cleaned = stories
        .filter((story) => story && story.title)
        .map((story, index) => ({
          id: story.id,
          title: story.title,
          source: "Hacker News",
          category: assignCategory(story.title),
          time: formatTime(story.time),
          readingTime: `${(index % 5) + 2} min read`,
          url:
            story.url ||
            `https://news.ycombinator.com/item?id=${story.id}`,
          thumbnail: `https://picsum.photos/seed/news${story.id}/500/300`,
        }));

      setNews(cleaned.length ? cleaned : fallbackNews);
      setLastUpdated(new Date());
    } catch (error) {
      console.error("Could not load news:", error);
      setNews(fallbackNews);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadNews();
  }, []);

  useEffect(() => {
    localStorage.setItem(
      "newsBookmarks",
      JSON.stringify(bookmarks)
    );
  }, [bookmarks]);

  useEffect(() => {
    localStorage.setItem(
      "newsDarkMode",
      String(darkMode)
    );
  }, [darkMode]);

  const filteredNews = useMemo(() => {
    const query = search.toLowerCase();

    return news.filter((article) => {
      const matchesCategory =
        category === "All" || article.category === category;

      const matchesSearch =
        article.title.toLowerCase().includes(query) ||
        article.source.toLowerCase().includes(query) ||
        article.category.toLowerCase().includes(query);

      return matchesCategory && matchesSearch;
    });
  }, [news, search, category]);

  const filteredRepos = useMemo(() => {
    const query = search.toLowerCase();

    return githubRepos.filter((repo) => {
      const matchesCategory =
        category === "All" || repo.category === category;

      const matchesSearch =
        repo.name.toLowerCase().includes(query) ||
        repo.language.toLowerCase().includes(query) ||
        repo.description.toLowerCase().includes(query) ||
        repo.category.toLowerCase().includes(query);

      return matchesCategory && matchesSearch;
    });
  }, [search, category]);

  useEffect(() => {
    function handleScroll() {
      const nearBottom =
        window.innerHeight + window.scrollY >=
        document.documentElement.scrollHeight - 250;

      if (nearBottom) {
        setVisibleCount((count) =>
          Math.min(count + 6, filteredNews.length)
        );
      }
    }

    window.addEventListener("scroll", handleScroll);

    return () => {
      window.removeEventListener("scroll", handleScroll);
    };
  }, [filteredNews.length]);

  function toggleBookmark(article) {
    const exists = bookmarks.some(
      (bookmark) => bookmark.id === article.id
    );

    if (exists) {
      setBookmarks(
        bookmarks.filter(
          (bookmark) => bookmark.id !== article.id
        )
      );
    } else {
      setBookmarks([...bookmarks, article]);
    }
  }

  function isBookmarked(id) {
    return bookmarks.some(
      (bookmark) => bookmark.id === id
    );
  }

  return (
    <div
      className={
        darkMode
          ? "min-h-screen bg-slate-950 text-white"
          : "min-h-screen bg-slate-100 text-slate-900"
      }
    >
      <header
        className={
          darkMode
            ? "sticky top-0 z-50 border-b border-slate-700 bg-slate-900"
            : "sticky top-0 z-50 border-b bg-white"
        }
      >
        <div className="mx-auto flex max-w-7xl flex-col gap-4 px-5 py-5 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h1 className="text-2xl font-bold">
              🌍 Global Tech News
            </h1>

            <p className="text-sm opacity-70">
              Technology news from around the world
            </p>
          </div>

          <div className="flex flex-1 flex-col gap-3 md:flex-row lg:max-w-3xl">
            <input
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setVisibleCount(6);
              }}
              placeholder="Search news, repos or categories..."
              className={
                darkMode
                  ? "flex-1 rounded-xl border border-slate-700 bg-slate-800 px-4 py-3 text-white outline-none focus:ring-2 focus:ring-blue-500"
                  : "flex-1 rounded-xl border border-slate-300 bg-white px-4 py-3 outline-none focus:ring-2 focus:ring-blue-500"
              }
            />

            <button
              onClick={() => setDarkMode(!darkMode)}
              className="rounded-xl bg-blue-600 px-5 py-3 font-semibold text-white hover:bg-blue-700"
            >
              {darkMode ? "☀ Light" : "🌙 Dark"}
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-5 py-8">
        <div className="mb-6 flex flex-wrap gap-2">
          {categories.map((item) => (
            <button
              key={item}
              onClick={() => {
                setCategory(item);
                setVisibleCount(6);
              }}
              className={
                category === item
                  ? "rounded-full bg-blue-600 px-4 py-2 text-sm font-semibold text-white"
                  : darkMode
                  ? "rounded-full bg-slate-800 px-4 py-2 text-sm hover:bg-slate-700"
                  : "rounded-full bg-white px-4 py-2 text-sm shadow hover:bg-slate-200"
              }
            >
              {item}
            </button>
          ))}
        </div>

        <section className="mb-12">
          <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-2xl font-bold">
                🔥 Trending News
              </h2>

              <p className="text-sm opacity-70">
                Last updated: {lastUpdated.toLocaleTimeString()}
              </p>
            </div>

            <button
              onClick={loadNews}
              className="rounded-lg bg-green-600 px-4 py-2 font-semibold text-white hover:bg-green-700"
            >
              Refresh
            </button>
          </div>

          {loading ? (
            <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
              {[1, 2, 3, 4, 5, 6].map((item) => (
                <div
                  key={item}
                  className={
                    darkMode
                      ? "animate-pulse rounded-2xl bg-slate-800 p-5"
                      : "animate-pulse rounded-2xl bg-white p-5 shadow"
                  }
                >
                  <div className="mb-4 h-40 rounded-xl bg-slate-400/30" />
                  <div className="mb-3 h-5 rounded bg-slate-400/30" />
                  <div className="h-4 w-2/3 rounded bg-slate-400/30" />
                </div>
              ))}
            </div>
          ) : (
            <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
              {filteredNews
                .slice(0, visibleCount)
                .map((article) => (
                  <article
                    key={article.id}
                    className={
                      darkMode
                        ? "overflow-hidden rounded-2xl bg-slate-900 shadow-lg"
                        : "overflow-hidden rounded-2xl bg-white shadow-md"
                    }
                  >
                    <img
                      src={article.thumbnail}
                      alt=""
                      className="h-44 w-full object-cover"
                    />

                    <div className="p-5">
                      <span className="mb-3 inline-block rounded-full bg-blue-100 px-3 py-1 text-xs font-semibold text-blue-700">
                        {article.category}
                      </span>

                      <h3 className="mb-3 text-lg font-bold">
                        {article.title}
                      </h3>

                      <p className="mb-4 text-sm opacity-70">
                        {article.source} • {article.time} •{" "}
                        {article.readingTime}
                      </p>

                      <div className="flex flex-wrap gap-2">
                        <a
                          href={article.url}
                          target="_blank"
                          rel="noreferrer"
                          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700"
                        >
                          Read
                        </a>

                        <button
                          onClick={() =>
                            toggleBookmark(article)
                          }
                          className={
                            isBookmarked(article.id)
                              ? "rounded-lg bg-yellow-500 px-4 py-2 text-sm font-semibold text-white"
                              : "rounded-lg bg-slate-500 px-4 py-2 text-sm font-semibold text-white"
                          }
                        >
                          {isBookmarked(article.id)
                            ? "★ Saved"
                            : "☆ Bookmark"}
                        </button>
                      </div>
                    </div>
                  </article>
                ))}
            </div>
          )}

          {!loading && filteredNews.length === 0 && (
            <p className="py-10 text-center opacity-70">
              No news matched your search.
            </p>
          )}
        </section>

        <section className="mb-12">
          <h2 className="mb-5 text-2xl font-bold">
            💻 GitHub Trending
          </h2>

          <div className="grid gap-4 md:grid-cols-2">
            {filteredRepos.map((repo) => (
              <div
                key={repo.id}
                className={
                  darkMode
                    ? "rounded-2xl bg-slate-900 p-5"
                    : "rounded-2xl bg-white p-5 shadow"
                }
              >
                <div className="mb-2 flex items-start justify-between gap-3">
                  <a
                    href={repo.url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-lg font-bold text-blue-500 hover:underline"
                  >
                    {repo.name}
                  </a>

                  <span className="rounded-full bg-green-100 px-3 py-1 text-xs font-bold text-green-700">
                    {repo.growth}
                  </span>
                </div>

                <p className="mb-4 opacity-75">
                  {repo.description}
                </p>

                <div className="flex gap-5 text-sm opacity-75">
                  <span>⭐ {repo.stars}</span>
                  <span>● {repo.language}</span>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="mb-10">
          <h2 className="mb-5 text-2xl font-bold">
            🔖 Bookmarks
          </h2>

          {bookmarks.length === 0 ? (
            <div
              className={
                darkMode
                  ? "rounded-2xl bg-slate-900 p-8 text-center"
                  : "rounded-2xl bg-white p-8 text-center shadow"
              }
            >
              <p className="opacity-70">
                You have no saved articles yet.
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {bookmarks.map((article) => (
                <div
                  key={article.id}
                  className={
                    darkMode
                      ? "flex flex-col justify-between gap-3 rounded-xl bg-slate-900 p-4 md:flex-row md:items-center"
                      : "flex flex-col justify-between gap-3 rounded-xl bg-white p-4 shadow md:flex-row md:items-center"
                  }
                >
                  <div>
                    <strong>{article.title}</strong>

                    <p className="text-sm opacity-60">
                      {article.source} • {article.category}
                    </p>
                  </div>

                  <button
                    onClick={() =>
                      toggleBookmark(article)
                    }
                    className="rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white"
                  >
                    Remove
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>
      </main>

      <footer
        className={
          darkMode
            ? "border-t border-slate-800 bg-slate-900 py-8"
            : "border-t bg-white py-8"
        }
      >
        <div className="mx-auto flex max-w-7xl flex-col gap-3 px-5 md:flex-row md:items-center md:justify-between">
          <div>
            <strong>Global Tech News Dashboard</strong>

            <p className="text-sm opacity-60">
              Sources: Hacker News and GitHub.
            </p>
          </div>

          <div className="text-sm">
            Total loaded: <strong>{news.length}</strong>
          </div>
        </div>
      </footer>
    </div>
  );
}

export default App;