// ------------------------------
// SINGLE SOURCE OF TRUTH
// ------------------------------

const defaultState = {
  incomes: [],
  expenses: [],
  loans: [],
  fds: [],
  sips: [],
  stocks: []
};

let state = loadState();


// ------------------------------
// SAMPLE WATCHLIST DATA
// ------------------------------

const watchStocks = [
  {
    name: "TCS",
    sector: "Technology",
    price: 4125,
    performance: 3.2
  },
  {
    name: "Infosys",
    sector: "Technology",
    price: 1890,
    performance: 2.4
  },
  {
    name: "HDFC Bank",
    sector: "Banking",
    price: 1745,
    performance: 1.8
  },
  {
    name: "Reliance",
    sector: "Energy",
    price: 3025,
    performance: 4.1
  },
  {
    name: "Sun Pharma",
    sector: "Healthcare",
    price: 1690,
    performance: -0.8
  },
  {
    name: "Tata Motors",
    sector: "Automobile",
    price: 980,
    performance: 5.2
  }
];

let sortTopPerformers = false;


// ------------------------------
// LOCAL STORAGE
// ------------------------------

function loadState() {
  try {
    const stored = localStorage.getItem("financeTrackerState");

    if (!stored) {
      return structuredClone(defaultState);
    }

    const parsed = JSON.parse(stored);

    return {
      incomes: Array.isArray(parsed.incomes)
        ? parsed.incomes
        : [],

      expenses: Array.isArray(parsed.expenses)
        ? parsed.expenses
        : [],

      loans: Array.isArray(parsed.loans)
        ? parsed.loans
        : [],

      fds: Array.isArray(parsed.fds)
        ? parsed.fds
        : [],

      sips: Array.isArray(parsed.sips)
        ? parsed.sips
        : [],

      stocks: Array.isArray(parsed.stocks)
        ? parsed.stocks
        : []
    };

  } catch (error) {

    console.error(
      "Stored data was corrupted. Resetting safely.",
      error
    );

    return structuredClone(defaultState);
  }
}


function saveState() {

  localStorage.setItem(
    "financeTrackerState",
    JSON.stringify(state)
  );

}


// ------------------------------
// HELPERS
// ------------------------------

function generateId() {
  return Date.now() + Math.random();
}


function formatCurrency(amount) {

  return new Intl.NumberFormat(
    "en-IN",
    {
      style: "currency",
      currency: "INR",
      maximumFractionDigits: 2
    }
  ).format(Number(amount) || 0);

}


function escapeHTML(value) {

  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

}


function value(id) {
  return document.getElementById(id).value.trim();
}


function numberValue(id) {
  return Number(document.getElementById(id).value);
}


function clearInputs(ids) {

  ids.forEach(id => {
    document.getElementById(id).value = "";
  });

}


// ------------------------------
// TABS
// ------------------------------

document
  .querySelectorAll(".tab-btn")
  .forEach(button => {

    button.addEventListener("click", () => {

      document
        .querySelectorAll(".tab-btn")
        .forEach(btn => btn.classList.remove("active"));

      document
        .querySelectorAll(".tab-content")
        .forEach(section =>
          section.classList.remove("active")
        );

      button.classList.add("active");

      document
        .getElementById(button.dataset.tab)
        .classList.add("active");

    });

  });


// ------------------------------
// ADD INCOME
// ------------------------------

document
  .getElementById("addIncomeBtn")
  .addEventListener("click", () => {

    const name = value("incomeName");
    const amount = numberValue("incomeAmount");
    const date = value("incomeDate");

    if (!name || amount <= 0) {
      alert("Please enter a valid income source and amount.");
      return;
    }

    state.incomes.push({
      id: generateId(),
      name,
      amount,
      date
    });

    saveState();

    clearInputs([
      "incomeName",
      "incomeAmount",
      "incomeDate"
    ]);

    render();

  });


// ------------------------------
// QUICK INCOME
// ------------------------------

document
  .getElementById("quickIncomeBtn")
  .addEventListener("click", () => {

    const name = value("quickIncomeName");
    const amount = numberValue("quickIncomeAmount");

    if (!name || amount <= 0) {
      alert("Enter a valid income.");
      return;
    }

    state.incomes.push({
      id: generateId(),
      name,
      amount,
      date: new Date().toISOString().split("T")[0]
    });

    saveState();

    clearInputs([
      "quickIncomeName",
      "quickIncomeAmount"
    ]);

    render();

  });


// ------------------------------
// ADD EXPENSE
// ------------------------------

document
  .getElementById("addExpenseBtn")
  .addEventListener("click", () => {

    const name = value("expenseName");
    const amount = numberValue("expenseAmount");
    const category = value("expenseCategory");
    const date = value("expenseDate");
    const why = value("expenseWhy");

    if (!name || amount <= 0) {
      alert("Please enter a valid expense.");
      return;
    }

    state.expenses.push({
      id: generateId(),
      name,
      amount,
      category,
      date,
      why
    });

    saveState();

    clearInputs([
      "expenseName",
      "expenseAmount",
      "expenseDate",
      "expenseWhy"
    ]);

    render();

  });


// ------------------------------
// QUICK EXPENSE
// ------------------------------

document
  .getElementById("quickExpenseBtn")
  .addEventListener("click", () => {

    const name = value("quickExpenseName");
    const amount = numberValue("quickExpenseAmount");

    if (!name || amount <= 0) {
      alert("Enter a valid expense.");
      return;
    }

    state.expenses.push({
      id: generateId(),
      name,
      amount,
      category: "Other",
      date: new Date().toISOString().split("T")[0],
      why: ""
    });

    saveState();

    clearInputs([
      "quickExpenseName",
      "quickExpenseAmount"
    ]);

    render();

  });


// ------------------------------
// ADD LOAN
// ------------------------------

document
  .getElementById("addLoanBtn")
  .addEventListener("click", () => {

    const name = value("loanName");
    const emi = numberValue("loanEmi");
    const rate = numberValue("loanRate");
    const months = numberValue("loanMonths");

    if (!name || emi <= 0 || months <= 0) {
      alert("Enter valid loan information.");
      return;
    }

    state.loans.push({
      id: generateId(),
      name,
      emi,
      rate,
      months
    });

    saveState();

    clearInputs([
      "loanName",
      "loanEmi",
      "loanRate",
      "loanMonths"
    ]);

    render();

  });


// ------------------------------
// ADD FD
// ------------------------------

document
  .getElementById("addFdBtn")
  .addEventListener("click", () => {

    const name = value("fdName");
    const principal = numberValue("fdPrincipal");
    const rate = numberValue("fdRate");
    const startDate = value("fdStartDate");
    const maturityDate = value("fdMaturityDate");

    if (!name || principal <= 0) {
      alert("Enter valid FD information.");
      return;
    }

    state.fds.push({
      id: generateId(),
      name,
      principal,
      rate,
      startDate,
      maturityDate
    });

    saveState();

    clearInputs([
      "fdName",
      "fdPrincipal",
      "fdRate",
      "fdStartDate",
      "fdMaturityDate"
    ]);

    render();

  });


// ------------------------------
// ADD SIP
// ------------------------------

document
  .getElementById("addSipBtn")
  .addEventListener("click", () => {

    const name = value("sipName");
    const monthly = numberValue("sipMonthly");
    const startDate = value("sipStartDate");

    if (!name || monthly <= 0 || !startDate) {
      alert("Enter valid SIP information.");
      return;
    }

    state.sips.push({
      id: generateId(),
      name,
      monthly,
      startDate
    });

    saveState();

    clearInputs([
      "sipName",
      "sipMonthly",
      "sipStartDate"
    ]);

    render();

  });


// ------------------------------
// ADD STOCK
// ------------------------------

document
  .getElementById("addStockBtn")
  .addEventListener("click", () => {

    const name = value("stockName");
    const sector = value("stockSector");
    const quantity = numberValue("stockQuantity");
    const buyPrice = numberValue("stockPrice");

    if (
      !name ||
      !sector ||
      quantity <= 0 ||
      buyPrice <= 0
    ) {

      alert("Enter valid stock information.");
      return;

    }

    state.stocks.push({
      id: generateId(),
      name,
      sector,
      quantity,
      buyPrice
    });

    saveState();

    clearInputs([
      "stockName",
      "stockSector",
      "stockQuantity",
      "stockPrice"
    ]);

    render();

  });


// ------------------------------
// DELETE ITEMS
// ------------------------------

function deleteItem(type, id) {

  state[type] = state[type].filter(
    item => item.id !== id
  );

  saveState();

  render();

}


// ------------------------------
// EDIT STOCK
// ------------------------------

function editStock(id) {

  const stock =
    state.stocks.find(item => item.id === id);

  if (!stock) return;

  const newName = prompt(
    "Stock name:",
    stock.name
  );

  if (newName === null) return;

  const newSector = prompt(
    "Sector:",
    stock.sector
  );

  if (newSector === null) return;

  const newQuantity = Number(
    prompt(
      "Quantity:",
      stock.quantity
    )
  );

  const newPrice = Number(
    prompt(
      "Buy price:",
      stock.buyPrice
    )
  );

  if (
    !newName.trim() ||
    !newSector.trim() ||
    newQuantity <= 0 ||
    newPrice <= 0
  ) {

    alert("Invalid stock information.");
    return;

  }

  stock.name = newName.trim();
  stock.sector = newSector.trim();
  stock.quantity = newQuantity;
  stock.buyPrice = newPrice;

  saveState();

  render();

}


// ------------------------------
// CALCULATIONS
// ------------------------------

function calculateTotals() {

  const income =
    state.incomes.reduce(
      (sum, item) =>
        sum + Number(item.amount),
      0
    );

  const expenses =
    state.expenses.reduce(
      (sum, item) =>
        sum + Number(item.amount),
      0
    );

  const emi =
    state.loans.reduce(
      (sum, loan) =>
        sum + Number(loan.emi),
      0
    );

  const sip =
    state.sips.reduce(
      (sum, item) =>
        sum + Number(item.monthly),
      0
    );

  const debt =
    state.loans.reduce(
      (sum, loan) =>
        sum +
        Number(loan.emi) *
        Number(loan.months),
      0
    );

  const fdValue =
    state.fds.reduce(
      (sum, fd) => {

        // The assignment requests money invested,
        // not fake investment returns.
        return sum + Number(fd.principal);

      },
      0
    );

  const sipContributed =
    state.sips.reduce(
      (sum, sipItem) => {

        const start =
          new Date(sipItem.startDate);

        const today = new Date();

        if (Number.isNaN(start.getTime())) {
          return sum;
        }

        let months =
          (today.getFullYear() - start.getFullYear())
          * 12;

        months +=
          today.getMonth() - start.getMonth();

        months += 1;

        months = Math.max(months, 0);

        return (
          sum +
          months *
          Number(sipItem.monthly)
        );

      },
      0
    );

  const stocksInvested =
    state.stocks.reduce(
      (sum, stock) =>
        sum +
        Number(stock.quantity) *
        Number(stock.buyPrice),
      0
    );

  const netCashFlow =
    income -
    expenses -
    emi -
    sip;

  return {
    income,
    expenses,
    emi,
    sip,
    debt,
    fdValue,
    sipContributed,
    stocksInvested,
    netCashFlow
  };

}


// ------------------------------
// DASHBOARD
// ------------------------------

function renderDashboard() {

  const totals = calculateTotals();

  document.getElementById(
    "incomeTotal"
  ).textContent =
    formatCurrency(totals.income);

  document.getElementById(
    "expenseTotal"
  ).textContent =
    formatCurrency(totals.expenses);

  document.getElementById(
    "emiTotal"
  ).textContent =
    formatCurrency(totals.emi);

  document.getElementById(
    "sipTotal"
  ).textContent =
    formatCurrency(totals.sip);

  document.getElementById(
    "debtTotal"
  ).textContent =
    formatCurrency(totals.debt);

  document.getElementById(
    "fdTotal"
  ).textContent =
    formatCurrency(totals.fdValue);

  document.getElementById(
    "sipContributionTotal"
  ).textContent =
    formatCurrency(
      totals.sipContributed
    );

  document.getElementById(
    "stocksTotal"
  ).textContent =
    formatCurrency(
      totals.stocksInvested
    );

  document.getElementById(
    "netCashFlow"
  ).textContent =
    formatCurrency(
      totals.netCashFlow
    );

  const cashFlowBox =
    document.getElementById(
      "cashFlowBox"
    );

  cashFlowBox.classList.remove(
    "positive",
    "negative"
  );

  cashFlowBox.classList.add(
    totals.netCashFlow >= 0
      ? "positive"
      : "negative"
  );

  const income =
    totals.income || 1;

  const expensePercent =
    Math.min(
      (totals.expenses / income) * 100,
      100
    );

  const emiPercent =
    Math.min(
      (totals.emi / income) * 100,
      100
    );

  const sipPercent =
    Math.min(
      (totals.sip / income) * 100,
      100
    );

  document.getElementById(
    "expenseFlow"
  ).style.width =
    `${expensePercent}%`;

  document.getElementById(
    "emiFlow"
  ).style.width =
    `${emiPercent}%`;

  document.getElementById(
    "sipFlow"
  ).style.width =
    `${sipPercent}%`;

}


// ------------------------------
// INCOME LIST
// ------------------------------

function renderIncome() {

  const container =
    document.getElementById(
      "incomeList"
    );

  if (!state.incomes.length) {

    container.innerHTML =
      '<p class="empty-message">No income added yet.</p>';

    return;

  }

  container.innerHTML =
    state.incomes
      .map(item => `

        <div class="item">

          <div class="item-details">

            <strong>
              ${escapeHTML(item.name)}
            </strong>

            <small>
              ${escapeHTML(item.date || "No date")}
            </small>

          </div>

          <div>

            <strong>
              ${formatCurrency(item.amount)}
            </strong>

            <button
              class="delete-btn"
              onclick="deleteItem('incomes', ${item.id})"
            >
              Delete
            </button>

          </div>

        </div>

      `)
      .join("");

}


// ------------------------------
// EXPENSE LIST
// ------------------------------

function renderExpenses() {

  const container =
    document.getElementById(
      "expenseList"
    );

  const filter =
    document.getElementById(
      "expenseFilter"
    ).value;

  const filtered =
    filter === "All"
      ? state.expenses
      : state.expenses.filter(
          item =>
            item.category === filter
        );

  if (!filtered.length) {

    container.innerHTML =
      '<p class="empty-message">No expenses found.</p>';

    return;

  }

  container.innerHTML =
    filtered
      .map(item => `

        <div class="item">

          <div class="item-details">

            <strong>
              ${escapeHTML(item.name)}
            </strong>

            <small>
              ${escapeHTML(item.category)}
              •
              ${escapeHTML(item.date || "No date")}
            </small>

            ${
              item.why
                ? `<small>
                     Why: ${escapeHTML(item.why)}
                   </small>`
                : ""
            }

          </div>

          <div>

            <strong>
              ${formatCurrency(item.amount)}
            </strong>

            <button
              class="delete-btn"
              onclick="deleteItem('expenses', ${item.id})"
            >
              Delete
            </button>

          </div>

        </div>

      `)
      .join("");

}


document
  .getElementById("expenseFilter")
  .addEventListener(
    "change",
    renderExpenses
  );


// ------------------------------
// LOANS
// ------------------------------

function renderLoans() {

  const container =
    document.getElementById(
      "loanList"
    );

  if (!state.loans.length) {

    container.innerHTML =
      '<p class="empty-message">No loans added.</p>';

    return;

  }

  container.innerHTML =
    state.loans
      .map(loan => `

        <div class="item">

          <div class="item-details">

            <strong>
              ${escapeHTML(loan.name)}
            </strong>

            <small>
              EMI:
              ${formatCurrency(loan.emi)}
              •
              Rate:
              ${loan.rate}%
              •
              ${loan.months} months left
            </small>

          </div>

          <button
            class="delete-btn"
            onclick="deleteItem('loans', ${loan.id})"
          >
            Delete
          </button>

        </div>

      `)
      .join("");

}


// ------------------------------
// FIXED DEPOSITS
// ------------------------------

function renderFds() {

  const container =
    document.getElementById(
      "fdList"
    );

  if (!state.fds.length) {

    container.innerHTML =
      '<p class="empty-message">No fixed deposits added.</p>';

    return;

  }

  container.innerHTML =
    state.fds
      .map(fd => `

        <div class="item">

          <div class="item-details">

            <strong>
              ${escapeHTML(fd.name)}
            </strong>

            <small>
              Principal:
              ${formatCurrency(fd.principal)}
              •
              Rate:
              ${fd.rate}%
            </small>

            <small>
              ${escapeHTML(fd.startDate || "")}
              →
              ${escapeHTML(fd.maturityDate || "")}
            </small>

          </div>

          <button
            class="delete-btn"
            onclick="deleteItem('fds', ${fd.id})"
          >
            Delete
          </button>

        </div>

      `)
      .join("");

}


// ------------------------------
// SIP LIST
// ------------------------------

function renderSips() {

  const container =
    document.getElementById(
      "sipList"
    );

  if (!state.sips.length) {

    container.innerHTML =
      '<p class="empty-message">No SIPs added.</p>';

    return;

  }

  container.innerHTML =
    state.sips
      .map(sip => `

        <div class="item">

          <div class="item-details">

            <strong>
              ${escapeHTML(sip.name)}
            </strong>

            <small>
              Monthly:
              ${formatCurrency(sip.monthly)}
              •
              Started:
              ${escapeHTML(sip.startDate)}
            </small>

          </div>

          <button
            class="delete-btn"
            onclick="deleteItem('sips', ${sip.id})"
          >
            Delete
          </button>

        </div>

      `)
      .join("");

}


// ------------------------------
// STOCK LIST
// ------------------------------

function renderStocks() {

  const container =
    document.getElementById(
      "stockList"
    );

  if (!state.stocks.length) {

    container.innerHTML =
      '<p class="empty-message">No stocks added.</p>';

    return;

  }

  container.innerHTML =
    state.stocks
      .map(stock => `

        <div class="item">

          <div class="item-details">

            <strong>
              ${escapeHTML(stock.name)}
            </strong>

            <small>
              ${escapeHTML(stock.sector)}
              •
              Quantity:
              ${stock.quantity}
              •
              Buy price:
              ${formatCurrency(stock.buyPrice)}
            </small>

            <small>
              Amount invested:
              ${formatCurrency(
                stock.quantity *
                stock.buyPrice
              )}
            </small>

          </div>

          <div class="actions">

            <button
              class="edit-btn"
              onclick="editStock(${stock.id})"
            >
              Edit
            </button>

            <button
              class="delete-btn"
              onclick="deleteItem('stocks', ${stock.id})"
            >
              Delete
            </button>

          </div>

        </div>

      `)
      .join("");

}


// ------------------------------
// WATCHLIST
// ------------------------------

function populateWatchSectors() {

  const select =
    document.getElementById(
      "watchSectorFilter"
    );

  const sectors =
    [
      ...new Set(
        watchStocks.map(
          stock => stock.sector
        )
      )
    ];

  select.innerHTML =
    '<option value="All">All Sectors</option>' +
    sectors
      .map(
        sector =>
          `<option value="${escapeHTML(sector)}">
             ${escapeHTML(sector)}
           </option>`
      )
      .join("");

}


function renderWatchlist() {

  const filter =
    document.getElementById(
      "watchSectorFilter"
    ).value;

  let stocks =
    filter === "All"
      ? [...watchStocks]
      : watchStocks.filter(
          stock =>
            stock.sector === filter
        );

  if (sortTopPerformers) {

    stocks.sort(
      (a, b) =>
        b.performance -
        a.performance
    );

  }

  document.getElementById(
    "watchList"
  ).innerHTML =
    stocks
      .map(stock => {

        const className =
          stock.performance >= 0
            ? "stock-performance-positive"
            : "stock-performance-negative";

        return `

          <div class="item">

            <div class="item-details">

              <strong>
                ${escapeHTML(stock.name)}
              </strong>

              <small>
                ${escapeHTML(stock.sector)}
              </small>

            </div>

            <div>

              <strong>
                ${formatCurrency(stock.price)}
              </strong>

              <div class="${className}">
                ${
                  stock.performance >= 0
                    ? "+"
                    : ""
                }${stock.performance}%
              </div>

            </div>

          </div>

        `;

      })
      .join("");

}


document
  .getElementById("watchSectorFilter")
  .addEventListener(
    "change",
    renderWatchlist
  );


document
  .getElementById("sortPerformersBtn")
  .addEventListener(
    "click",
    () => {

      sortTopPerformers =
        !sortTopPerformers;

      renderWatchlist();

    }
  );


// ------------------------------
// MAIN RENDER
// ------------------------------

function render() {

  renderDashboard();

  renderIncome();

  renderExpenses();

  renderLoans();

  renderFds();

  renderSips();

  renderStocks();

}


// ------------------------------
// START APPLICATION
// ------------------------------

populateWatchSectors();

renderWatchlist();

render();