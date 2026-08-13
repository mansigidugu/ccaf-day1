import { useEffect, useMemo, useState } from "react";

function App() {
  const [countries, setCountries] = useState([]);
  const [search, setSearch] = useState("");
  const [selectedCountry, setSelectedCountry] = useState(null);

  const [compareA, setCompareA] = useState("");
  const [compareB, setCompareB] = useState("");

  const [loading, setLoading] = useState(true);

  const [darkMode, setDarkMode] = useState(() => {
    return localStorage.getItem("countryDarkMode") === "true";
  });

  const [favorites, setFavorites] = useState(() => {
    try {
      return JSON.parse(
        localStorage.getItem("countryFavorites")
      ) || [];
    } catch {
      return [];
    }
  });

  // -----------------------------
  // FETCH COUNTRIES
  // -----------------------------

  useEffect(() => {
    async function loadCountries() {
      try {
        setLoading(true);

        const response = await fetch(
          "https://restcountries.com/v3.1/all?fields=name,capital,population,area,region,subregion,timezones,flags,coatOfArms,currencies,languages,borders,latlng,continents,idd,tld,car,landlocked,cca3,maps"
        );

        if (!response.ok) {
          throw new Error("Could not fetch countries.");
        }

        const data = await response.json();

        const sorted = data.sort((a, b) =>
          a.name.common.localeCompare(b.name.common)
        );

        setCountries(sorted);

        if (sorted.length > 0) {
          setSelectedCountry(sorted[0]);
        }
      } catch (error) {
        console.error(error);
      } finally {
        setLoading(false);
      }
    }

    loadCountries();
  }, []);

  // -----------------------------
  // LOCAL STORAGE
  // -----------------------------

  useEffect(() => {
    localStorage.setItem(
      "countryFavorites",
      JSON.stringify(favorites)
    );
  }, [favorites]);

  useEffect(() => {
    localStorage.setItem(
      "countryDarkMode",
      String(darkMode)
    );
  }, [darkMode]);

  // -----------------------------
  // HELPERS
  // -----------------------------

  function formatNumber(value) {
    return new Intl.NumberFormat("en-US").format(
      Number(value) || 0
    );
  }

  function getCapital(country) {
    return country?.capital?.[0] || "N/A";
  }

  function getCurrencies(country) {
    if (!country?.currencies) {
      return "N/A";
    }

    return Object.values(country.currencies)
      .map((currency) => {
        return `${currency.name} (${currency.symbol || "No symbol"})`;
      })
      .join(", ");
  }

  function getCurrencyCodes(country) {
    if (!country?.currencies) {
      return "";
    }

    return Object.keys(country.currencies).join(", ");
  }

  function getLanguages(country) {
    if (!country?.languages) {
      return "N/A";
    }

    return Object.values(country.languages).join(", ");
  }

  function getCallingCode(country) {
    if (!country?.idd?.root) {
      return "N/A";
    }

    const suffix =
      country.idd.suffixes?.[0] || "";

    return `${country.idd.root}${suffix}`;
  }

  function getDensity(country) {
    if (!country?.population || !country?.area) {
      return 0;
    }

    return country.population / country.area;
  }

  function getCoastlineStatus(country) {
    if (country?.landlocked === true) {
      return "Landlocked";
    }

    return "Has coastline";
  }

  // -----------------------------
  // SEARCH
  // -----------------------------

  const filteredCountries = useMemo(() => {
    const query = search.trim().toLowerCase();

    if (!query) {
      return countries.slice(0, 12);
    }

    return countries
      .filter((country) => {
        const name =
          country.name?.common?.toLowerCase() || "";

        const official =
          country.name?.official?.toLowerCase() || "";

        const capital =
          country.capital?.join(" ").toLowerCase() || "";

        const region =
          country.region?.toLowerCase() || "";

        const subregion =
          country.subregion?.toLowerCase() || "";

        const currencyCodes =
          getCurrencyCodes(country).toLowerCase();

        const currencies =
          getCurrencies(country).toLowerCase();

        const languages =
          getLanguages(country).toLowerCase();

        return (
          name.includes(query) ||
          official.includes(query) ||
          capital.includes(query) ||
          region.includes(query) ||
          subregion.includes(query) ||
          currencyCodes.includes(query) ||
          currencies.includes(query) ||
          languages.includes(query)
        );
      })
      .slice(0, 20);
  }, [search, countries]);

  // -----------------------------
  // FAVORITES
  // -----------------------------

  function isFavorite(country) {
    return favorites.some(
      (favorite) =>
        favorite.cca3 === country.cca3
    );
  }

  function toggleFavorite(country) {
    if (isFavorite(country)) {
      setFavorites(
        favorites.filter(
          (favorite) =>
            favorite.cca3 !== country.cca3
        )
      );
    } else {
      setFavorites([
        ...favorites,
        {
          cca3: country.cca3,
          name: country.name.common,
          flag: country.flags?.svg,
        },
      ]);
    }
  }

  // -----------------------------
  // COUNTRY CARD
  // -----------------------------

  function CountryCard({ country }) {
    return (
      <button
        onClick={() =>
          setSelectedCountry(country)
        }
        className={
          darkMode
            ? "rounded-2xl bg-slate-900 p-5 text-left shadow-lg transition hover:-translate-y-1"
            : "rounded-2xl bg-white p-5 text-left shadow transition hover:-translate-y-1"
        }
      >
        <img
          src={country.flags?.svg}
          alt={`${country.name.common} flag`}
          className="mb-4 h-32 w-full rounded-xl object-cover"
        />

        <h3 className="text-xl font-bold">
          {country.name.common}
        </h3>

        <p className="mt-2 text-sm opacity-70">
          Capital: {getCapital(country)}
        </p>

        <p className="text-sm opacity-70">
          Region: {country.region}
        </p>

        <p className="text-sm opacity-70">
          Population:{" "}
          {formatNumber(country.population)}
        </p>
      </button>
    );
  }

  // -----------------------------
  // COMPARE COUNTRY
  // -----------------------------

  const countryA = countries.find(
    (country) =>
      country.cca3 === compareA
  );

  const countryB = countries.find(
    (country) =>
      country.cca3 === compareB
  );

  function CompareColumn({ country }) {
    if (!country) {
      return (
        <div className="p-6 text-center opacity-60">
          Select a country
        </div>
      );
    }

    return (
      <div className="p-6">
        <img
          src={country.flags?.svg}
          alt=""
          className="mx-auto mb-4 h-24 w-36 rounded-lg object-cover"
        />

        <h3 className="mb-5 text-center text-xl font-bold">
          {country.name.common}
        </h3>

        <div className="space-y-3 text-sm">
          <p>
            <strong>Capital:</strong>{" "}
            {getCapital(country)}
          </p>

          <p>
            <strong>Population:</strong>{" "}
            {formatNumber(country.population)}
          </p>

          <p>
            <strong>Area:</strong>{" "}
            {formatNumber(country.area)} km²
          </p>

          <p>
            <strong>Region:</strong>{" "}
            {country.region}
          </p>

          <p>
            <strong>Languages:</strong>{" "}
            {getLanguages(country)}
          </p>

          <p>
            <strong>Currency:</strong>{" "}
            {getCurrencies(country)}
          </p>

          <p>
            <strong>Density:</strong>{" "}
            {getDensity(country).toFixed(2)} people/km²
          </p>

          <p>
            <strong>Driving:</strong>{" "}
            {country.car?.side || "N/A"}
          </p>
        </div>
      </div>
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
      {/* HEADER */}

      <header
        className={
          darkMode
            ? "sticky top-0 z-50 border-b border-slate-700 bg-slate-900"
            : "sticky top-0 z-50 border-b bg-white"
        }
      >
        <div className="mx-auto flex max-w-7xl flex-col gap-4 px-5 py-5 md:flex-row md:items-center md:justify-between">
          <div>
            <h1 className="text-2xl font-bold">
              🌎 Country Intelligence
            </h1>

            <p className="text-sm opacity-70">
              Explore countries around the world
            </p>
          </div>

          <button
            onClick={() =>
              setDarkMode(!darkMode)
            }
            className="rounded-xl bg-blue-600 px-5 py-3 font-semibold text-white hover:bg-blue-700"
          >
            {darkMode
              ? "☀ Light Mode"
              : "🌙 Dark Mode"}
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-5 py-8">

        {/* SEARCH */}

        <section className="mb-10">
          <h2 className="mb-4 text-2xl font-bold">
            Search Countries
          </h2>

          <input
            value={search}
            onChange={(event) =>
              setSearch(event.target.value)
            }
            placeholder="Search by name, capital, region, currency or language..."
            className={
              darkMode
                ? "w-full rounded-xl border border-slate-700 bg-slate-900 px-5 py-4 text-white outline-none focus:ring-2 focus:ring-blue-500"
                : "w-full rounded-xl border border-slate-300 bg-white px-5 py-4 outline-none focus:ring-2 focus:ring-blue-500"
            }
          />
        </section>

        {/* LOADING */}

        {loading ? (
          <div className="py-20 text-center">
            <p className="text-xl">
              Loading countries...
            </p>
          </div>
        ) : (
          <>
            {/* SEARCH RESULTS */}

            <section className="mb-12">
              <h2 className="mb-5 text-2xl font-bold">
                Countries
              </h2>

              <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {filteredCountries.map(
                  (country) => (
                    <CountryCard
                      key={country.cca3}
                      country={country}
                    />
                  )
                )}
              </div>
            </section>

            {/* SELECTED COUNTRY */}

            {selectedCountry && (
              <section className="mb-12">

                <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
                  <h2 className="text-3xl font-bold">
                    {selectedCountry.name.common}
                  </h2>

                  <button
                    onClick={() =>
                      toggleFavorite(selectedCountry)
                    }
                    className={
                      isFavorite(selectedCountry)
                        ? "rounded-xl bg-yellow-500 px-5 py-3 font-bold text-white"
                        : "rounded-xl bg-blue-600 px-5 py-3 font-bold text-white"
                    }
                  >
                    {isFavorite(selectedCountry)
                      ? "★ Favorite"
                      : "☆ Add Favorite"}
                  </button>
                </div>

                {/* OVERVIEW */}

                <div
                  className={
                    darkMode
                      ? "mb-6 grid gap-6 rounded-2xl bg-slate-900 p-6 lg:grid-cols-3"
                      : "mb-6 grid gap-6 rounded-2xl bg-white p-6 shadow lg:grid-cols-3"
                  }
                >
                  <div>
                    <img
                      src={
                        selectedCountry.flags?.svg
                      }
                      alt={`${selectedCountry.name.common} flag`}
                      className="h-48 w-full rounded-xl object-cover"
                    />
                  </div>

                  <div className="lg:col-span-2">
                    <h3 className="mb-4 text-xl font-bold">
                      Overview
                    </h3>

                    <div className="grid gap-3 md:grid-cols-2">
                      <p>
                        <strong>Official Name:</strong>{" "}
                        {
                          selectedCountry.name
                            .official
                        }
                      </p>

                      <p>
                        <strong>Capital:</strong>{" "}
                        {getCapital(
                          selectedCountry
                        )}
                      </p>

                      <p>
                        <strong>Population:</strong>{" "}
                        {formatNumber(
                          selectedCountry.population
                        )}
                      </p>

                      <p>
                        <strong>Area:</strong>{" "}
                        {formatNumber(
                          selectedCountry.area
                        )}{" "}
                        km²
                      </p>

                      <p>
                        <strong>Region:</strong>{" "}
                        {selectedCountry.region}
                      </p>

                      <p>
                        <strong>Subregion:</strong>{" "}
                        {selectedCountry.subregion ||
                          "N/A"}
                      </p>

                      <p className="md:col-span-2">
                        <strong>Timezone:</strong>{" "}
                        {selectedCountry.timezones?.join(
                          ", "
                        )}
                      </p>
                    </div>
                  </div>
                </div>

                {/* STATISTICS */}

                <h3 className="mb-4 text-xl font-bold">
                  Statistics
                </h3>

                <div className="mb-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
                  {[
                    [
                      "Density",
                      `${getDensity(
                        selectedCountry
                      ).toFixed(2)} / km²`,
                    ],

                    [
                      "Area",
                      `${formatNumber(
                        selectedCountry.area
                      )} km²`,
                    ],

                    [
                      "Borders",
                      selectedCountry.borders
                        ?.length || 0,
                    ],

                    [
                      "Time Zones",
                      selectedCountry.timezones
                        ?.length || 0,
                    ],

                    [
                      "Languages",
                      selectedCountry.languages
                        ? Object.keys(
                            selectedCountry.languages
                          ).length
                        : 0,
                    ],
                  ].map(([label, data]) => (
                    <div
                      key={label}
                      className={
                        darkMode
                          ? "rounded-xl bg-slate-900 p-5"
                          : "rounded-xl bg-white p-5 shadow"
                      }
                    >
                      <p className="text-sm opacity-60">
                        {label}
                      </p>

                      <strong className="text-xl">
                        {data}
                      </strong>
                    </div>
                  ))}
                </div>

                {/* INFORMATION SECTIONS */}

                <div className="grid gap-6 lg:grid-cols-3">

                  {/* GEOGRAPHY */}

                  <div
                    className={
                      darkMode
                        ? "rounded-2xl bg-slate-900 p-6"
                        : "rounded-2xl bg-white p-6 shadow"
                    }
                  >
                    <h3 className="mb-4 text-xl font-bold">
                      🗺 Geography
                    </h3>

                    <div className="space-y-3">
                      <p>
                        <strong>
                          Continent:
                        </strong>{" "}
                        {selectedCountry.continents?.join(
                          ", "
                        )}
                      </p>

                      <p>
                        <strong>Borders:</strong>{" "}
                        {selectedCountry.borders
                          ?.length
                          ? selectedCountry.borders.join(
                              ", "
                            )
                          : "None"}
                      </p>

                      <p>
                        <strong>
                          Coordinates:
                        </strong>{" "}
                        {selectedCountry.latlng?.join(
                          ", "
                        )}
                      </p>

                      <p>
                        <strong>
                          Coastline:
                        </strong>{" "}
                        {getCoastlineStatus(
                          selectedCountry
                        )}
                      </p>

                      {selectedCountry.maps?.googleMaps && (
                        <a
                          href={
                            selectedCountry.maps
                              .googleMaps
                          }
                          target="_blank"
                          rel="noreferrer"
                          className="inline-block rounded-lg bg-blue-600 px-4 py-2 font-semibold text-white"
                        >
                          Open Map
                        </a>
                      )}
                    </div>
                  </div>

                  {/* LANGUAGE/CURRENCY */}

                  <div
                    className={
                      darkMode
                        ? "rounded-2xl bg-slate-900 p-6"
                        : "rounded-2xl bg-white p-6 shadow"
                    }
                  >
                    <h3 className="mb-4 text-xl font-bold">
                      💬 Language & Currency
                    </h3>

                    <div className="space-y-3">
                      <p>
                        <strong>
                          Languages:
                        </strong>{" "}
                        {getLanguages(
                          selectedCountry
                        )}
                      </p>

                      <p>
                        <strong>
                          Currency:
                        </strong>{" "}
                        {getCurrencies(
                          selectedCountry
                        )}
                      </p>

                      <p>
                        <strong>
                          Currency Code:
                        </strong>{" "}
                        {getCurrencyCodes(
                          selectedCountry
                        )}
                      </p>
                    </div>
                  </div>

                  {/* NATIONAL INFO */}

                  <div
                    className={
                      darkMode
                        ? "rounded-2xl bg-slate-900 p-6"
                        : "rounded-2xl bg-white p-6 shadow"
                    }
                  >
                    <h3 className="mb-4 text-xl font-bold">
                      🏛 National Info
                    </h3>

                    {selectedCountry.coatOfArms
                      ?.svg && (
                      <img
                        src={
                          selectedCountry
                            .coatOfArms.svg
                        }
                        alt="Coat of arms"
                        className="mb-4 h-24 max-w-full object-contain"
                      />
                    )}

                    <div className="space-y-3">
                      <p>
                        <strong>
                          Calling Code:
                        </strong>{" "}
                        {getCallingCode(
                          selectedCountry
                        )}
                      </p>

                      <p>
                        <strong>
                          Internet Domain:
                        </strong>{" "}
                        {selectedCountry.tld?.join(
                          ", "
                        ) || "N/A"}
                      </p>

                      <p>
                        <strong>
                          Driving Side:
                        </strong>{" "}
                        {selectedCountry.car
                          ?.side || "N/A"}
                      </p>
                    </div>
                  </div>
                </div>
              </section>
            )}

            {/* COMPARE */}

            <section className="mb-12">
              <h2 className="mb-5 text-2xl font-bold">
                ⚖️ Compare Countries
              </h2>

              <div className="mb-5 grid gap-4 md:grid-cols-2">
                <select
                  value={compareA}
                  onChange={(event) =>
                    setCompareA(
                      event.target.value
                    )
                  }
                  className={
                    darkMode
                      ? "rounded-xl border border-slate-700 bg-slate-900 p-4"
                      : "rounded-xl border bg-white p-4"
                  }
                >
                  <option value="">
                    Select Country A
                  </option>

                  {countries.map(
                    (country) => (
                      <option
                        key={country.cca3}
                        value={country.cca3}
                      >
                        {country.name.common}
                      </option>
                    )
                  )}
                </select>

                <select
                  value={compareB}
                  onChange={(event) =>
                    setCompareB(
                      event.target.value
                    )
                  }
                  className={
                    darkMode
                      ? "rounded-xl border border-slate-700 bg-slate-900 p-4"
                      : "rounded-xl border bg-white p-4"
                  }
                >
                  <option value="">
                    Select Country B
                  </option>

                  {countries.map(
                    (country) => (
                      <option
                        key={country.cca3}
                        value={country.cca3}
                      >
                        {country.name.common}
                      </option>
                    )
                  )}
                </select>
              </div>

              <div
                className={
                  darkMode
                    ? "grid overflow-hidden rounded-2xl bg-slate-900 md:grid-cols-2"
                    : "grid overflow-hidden rounded-2xl bg-white shadow md:grid-cols-2"
                }
              >
                <CompareColumn
                  country={countryA}
                />

                <CompareColumn
                  country={countryB}
                />
              </div>
            </section>

            {/* FAVORITES */}

            <section className="mb-10">
              <h2 className="mb-5 text-2xl font-bold">
                ❤️ Favorites
              </h2>

              {favorites.length === 0 ? (
                <div
                  className={
                    darkMode
                      ? "rounded-2xl bg-slate-900 p-8 text-center"
                      : "rounded-2xl bg-white p-8 text-center shadow"
                  }
                >
                  <p className="opacity-60">
                    No favorite countries yet.
                  </p>
                </div>
              ) : (
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                  {favorites.map(
                    (favorite) => (
                      <div
                        key={favorite.cca3}
                        className={
                          darkMode
                            ? "rounded-xl bg-slate-900 p-4"
                            : "rounded-xl bg-white p-4 shadow"
                        }
                      >
                        <img
                          src={favorite.flag}
                          alt=""
                          className="mb-3 h-24 w-full rounded-lg object-cover"
                        />

                        <strong>
                          {favorite.name}
                        </strong>

                        <button
                          onClick={() => {
                            setFavorites(
                              favorites.filter(
                                (item) =>
                                  item.cca3 !==
                                  favorite.cca3
                              )
                            );
                          }}
                          className="mt-3 block rounded-lg bg-red-600 px-3 py-2 text-sm font-semibold text-white"
                        >
                          Remove
                        </button>
                      </div>
                    )
                  )}
                </div>
              )}
            </section>
          </>
        )}
      </main>

      <footer
        className={
          darkMode
            ? "border-t border-slate-800 bg-slate-900 py-7"
            : "border-t bg-white py-7"
        }
      >
        <div className="mx-auto max-w-7xl px-5 text-center">
          <strong>
            Country Intelligence Dashboard
          </strong>

          <p className="mt-1 text-sm opacity-60">
            Country data powered by REST Countries
          </p>
        </div>
      </footer>
    </div>
  );
}

export default App;