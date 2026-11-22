"""Build an analysis-ready AdventureWorks SQLite database.

Expected input:
  - archive (4).zip containing the AdventureWorks CSV files, OR
  - the extracted CSV files in --data-dir.

Usage:
  python scripts.py
  python scripts.py --zip path/to/archive.zip --db company.db
  python scripts.py --data-dir ./csv_files --db company.db

Profit figures are estimates: the source sales CSVs contain quantities but
not transaction-level selling prices, discounts, tax, or shipping charges.
The script therefore uses Products.ProductPrice and Products.ProductCost.
"""

from __future__ import annotations

import argparse
import io
import sqlite3
import zipfile
from pathlib import Path

import pandas as pd


REQUIRED_FILES = [
    "AdventureWorks_Calendar.csv",
    "AdventureWorks_Customers.csv",
    "AdventureWorks_Product_Categories.csv",
    "AdventureWorks_Product_Subcategories.csv",
    "AdventureWorks_Products.csv",
    "AdventureWorks_Returns.csv",
    "AdventureWorks_Territories.csv",
    "AdventureWorks_Sales_2015.csv",
    "AdventureWorks_Sales_2016.csv",
    "AdventureWorks_Sales_2017.csv",
]

TABLES = [
    "calendar",
    "customers",
    "product_categories",
    "product_subcategories",
    "products",
    "territories",
    "sales",
    "returns",
]

VIEWS = [
    "sales_detail",
    "customer_analysis",
    "product_analysis",
    "category_analysis",
    "territory_analysis",
    "order_analysis",
    "return_analysis",
    "monthly_profit_analysis",
    "annual_profit_analysis",
    "company_profit_analysis",
]


def read_csv_from_zip_or_folder(
    filename: str,
    zip_file: zipfile.ZipFile | None,
    data_dir: Path,
) -> pd.DataFrame:
    """Read a CSV from the archive or from an extracted-data directory."""
    if zip_file is not None:
        # Match by basename, so a folder prefix inside the ZIP is harmless.
        matches = [name for name in zip_file.namelist() if Path(name).name == filename]
        if not matches:
            raise FileNotFoundError(f"{filename} was not found inside the ZIP archive.")
        with zip_file.open(matches[0]) as file_obj:
            df = pd.read_csv(file_obj, encoding="latin1")
    else:
        path = data_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {path}")
        df = pd.read_csv(path, encoding="latin1")

    df.columns = df.columns.str.strip()
    return df


def parse_us_date(series: pd.Series) -> pd.Series:
    """Convert source dates (M/D/YYYY) to ISO YYYY-MM-DD strings."""
    parsed = pd.to_datetime(series, format="%m/%d/%Y", errors="coerce")
    invalid = int(parsed.isna().sum() - series.isna().sum())
    if invalid:
        raise ValueError(f"Found {invalid} invalid date value(s). Example: {series[parsed.isna()].head(3).tolist()}")
    return parsed.dt.strftime("%Y-%m-%d")


def clean_text_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Trim whitespace without changing the actual text values."""
    for column in df.select_dtypes(include="object").columns:
        df[column] = df[column].map(lambda value: value.strip() if isinstance(value, str) else value)
    return df


def load_source_data(
    zip_file: zipfile.ZipFile | None,
    data_dir: Path,
) -> dict[str, pd.DataFrame]:
    """Load and standardize all ten source CSV files."""
    raw = {
        filename: clean_text_columns(read_csv_from_zip_or_folder(filename, zip_file, data_dir))
        for filename in REQUIRED_FILES
    }

    # Dimension tables.
    calendar = raw["AdventureWorks_Calendar.csv"].copy()
    calendar["Date"] = parse_us_date(calendar["Date"])
    calendar_dates = pd.to_datetime(calendar["Date"])
    calendar["Year"] = calendar_dates.dt.year
    calendar["Quarter"] = calendar_dates.dt.quarter
    calendar["Month"] = calendar_dates.dt.month
    calendar["MonthName"] = calendar_dates.dt.month_name()
    calendar["Day"] = calendar_dates.dt.day
    calendar["DayOfWeek"] = calendar_dates.dt.day_name()

    customers = raw["AdventureWorks_Customers.csv"].copy()
    customers["BirthDate"] = parse_us_date(customers["BirthDate"])
    customers["AnnualIncome"] = pd.to_numeric(
        customers["AnnualIncome"].astype("string").str.replace(r"[$,]", "", regex=True).str.strip(),
        errors="coerce",
    )
    customers["TotalChildren"] = pd.to_numeric(customers["TotalChildren"], errors="coerce")

    categories = raw["AdventureWorks_Product_Categories.csv"].copy()
    subcategories = raw["AdventureWorks_Product_Subcategories.csv"].copy()

    products = raw["AdventureWorks_Products.csv"].copy()
    for column in ["ProductCost", "ProductPrice"]:
        products[column] = pd.to_numeric(products[column], errors="coerce")
    products["ProductSubcategoryKey"] = pd.to_numeric(products["ProductSubcategoryKey"], errors="coerce")

    territories = raw["AdventureWorks_Territories.csv"].copy()

    # Sales is split across three yearly files; combine into one fact table.
    sales_frames = []
    for filename in [
        "AdventureWorks_Sales_2015.csv",
        "AdventureWorks_Sales_2016.csv",
        "AdventureWorks_Sales_2017.csv",
    ]:
        frame = raw[filename].copy()
        frame["OrderDate"] = parse_us_date(frame["OrderDate"])
        frame["StockDate"] = parse_us_date(frame["StockDate"])
        frame["SalesYear"] = pd.to_datetime(frame["OrderDate"]).dt.year
        frame["SourceFile"] = filename
        sales_frames.append(frame)

    sales = pd.concat(sales_frames, ignore_index=True)
    duplicate_mask = sales.duplicated(subset=["OrderNumber", "OrderLineItem"], keep=False)
    if duplicate_mask.any():
        examples = sales.loc[duplicate_mask, ["OrderNumber", "OrderLineItem"]].head(5).to_dict("records")
        raise ValueError(
            "Duplicate OrderNumber + OrderLineItem combinations found. "
            f"Resolve these before importing. Examples: {examples}"
        )

    for column in ["OrderQuantity", "OrderLineItem", "ProductKey", "CustomerKey", "TerritoryKey"]:
        sales[column] = pd.to_numeric(sales[column], errors="raise").astype("int64")

    returns = raw["AdventureWorks_Returns.csv"].copy()
    returns["ReturnDate"] = parse_us_date(returns["ReturnDate"])
    for column in ["TerritoryKey", "ProductKey", "ReturnQuantity"]:
        returns[column] = pd.to_numeric(returns[column], errors="raise").astype("int64")

    # Keep column order aligned with the SQLite table definitions.
    return {
        "calendar": calendar[["Date", "Year", "Quarter", "Month", "MonthName", "Day", "DayOfWeek"]],
        "customers": customers[[
            "CustomerKey", "Prefix", "FirstName", "LastName", "BirthDate", "MaritalStatus",
            "Gender", "EmailAddress", "AnnualIncome", "TotalChildren", "EducationLevel",
            "Occupation", "HomeOwner",
        ]],
        "product_categories": categories[["ProductCategoryKey", "CategoryName"]],
        "product_subcategories": subcategories[[
            "ProductSubcategoryKey", "SubcategoryName", "ProductCategoryKey",
        ]],
        "products": products[[
            "ProductKey", "ProductSubcategoryKey", "ProductSKU", "ProductName", "ModelName",
            "ProductDescription", "ProductColor", "ProductSize", "ProductStyle", "ProductCost",
            "ProductPrice",
        ]],
        "territories": territories[["SalesTerritoryKey", "Region", "Country", "Continent"]],
        "sales": sales[[
            "OrderDate", "StockDate", "OrderNumber", "ProductKey", "CustomerKey", "TerritoryKey",
            "OrderLineItem", "OrderQuantity", "SalesYear", "SourceFile",
        ]],
        "returns": returns[["ReturnDate", "TerritoryKey", "ProductKey", "ReturnQuantity"]],
    }


def create_schema(conn: sqlite3.Connection) -> None:
    """Rebuild the database's owned tables and views."""
    conn.execute("PRAGMA foreign_keys = OFF")

    for view_name in VIEWS:
        conn.execute(f'DROP VIEW IF EXISTS "{view_name}"')
    for table_name in reversed(TABLES):
        conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')

    conn.executescript(
        """
        CREATE TABLE calendar (
            Date TEXT PRIMARY KEY,
            Year INTEGER NOT NULL,
            Quarter INTEGER NOT NULL,
            Month INTEGER NOT NULL,
            MonthName TEXT NOT NULL,
            Day INTEGER NOT NULL,
            DayOfWeek TEXT NOT NULL
        );

        CREATE TABLE customers (
            CustomerKey INTEGER PRIMARY KEY,
            Prefix TEXT,
            FirstName TEXT,
            LastName TEXT,
            BirthDate TEXT,
            MaritalStatus TEXT,
            Gender TEXT,
            EmailAddress TEXT,
            AnnualIncome REAL,
            TotalChildren INTEGER,
            EducationLevel TEXT,
            Occupation TEXT,
            HomeOwner TEXT
        );

        CREATE TABLE product_categories (
            ProductCategoryKey INTEGER PRIMARY KEY,
            CategoryName TEXT NOT NULL
        );

        CREATE TABLE product_subcategories (
            ProductSubcategoryKey INTEGER PRIMARY KEY,
            SubcategoryName TEXT NOT NULL,
            ProductCategoryKey INTEGER NOT NULL,
            FOREIGN KEY (ProductCategoryKey) REFERENCES product_categories(ProductCategoryKey)
        );

        CREATE TABLE products (
            ProductKey INTEGER PRIMARY KEY,
            ProductSubcategoryKey INTEGER,
            ProductSKU TEXT,
            ProductName TEXT NOT NULL,
            ModelName TEXT,
            ProductDescription TEXT,
            ProductColor TEXT,
            ProductSize TEXT,
            ProductStyle TEXT,
            ProductCost REAL,
            ProductPrice REAL,
            FOREIGN KEY (ProductSubcategoryKey) REFERENCES product_subcategories(ProductSubcategoryKey)
        );

        CREATE TABLE territories (
            SalesTerritoryKey INTEGER PRIMARY KEY,
            Region TEXT,
            Country TEXT,
            Continent TEXT
        );

        CREATE TABLE sales (
            OrderDate TEXT NOT NULL,
            StockDate TEXT,
            OrderNumber TEXT NOT NULL,
            ProductKey INTEGER NOT NULL,
            CustomerKey INTEGER NOT NULL,
            TerritoryKey INTEGER NOT NULL,
            OrderLineItem INTEGER NOT NULL,
            OrderQuantity INTEGER NOT NULL,
            SalesYear INTEGER NOT NULL,
            SourceFile TEXT NOT NULL,
            PRIMARY KEY (OrderNumber, OrderLineItem),
            FOREIGN KEY (OrderDate) REFERENCES calendar(Date),
            FOREIGN KEY (ProductKey) REFERENCES products(ProductKey),
            FOREIGN KEY (CustomerKey) REFERENCES customers(CustomerKey),
            FOREIGN KEY (TerritoryKey) REFERENCES territories(SalesTerritoryKey)
        );

        CREATE TABLE returns (
            ReturnID INTEGER PRIMARY KEY AUTOINCREMENT,
            ReturnDate TEXT NOT NULL,
            TerritoryKey INTEGER NOT NULL,
            ProductKey INTEGER NOT NULL,
            ReturnQuantity INTEGER NOT NULL,
            FOREIGN KEY (ReturnDate) REFERENCES calendar(Date),
            FOREIGN KEY (TerritoryKey) REFERENCES territories(SalesTerritoryKey),
            FOREIGN KEY (ProductKey) REFERENCES products(ProductKey)
        );
        """
    )


def create_indexes(conn: sqlite3.Connection) -> None:
    indexes = [
        "CREATE INDEX idx_sales_order_date ON sales(OrderDate)",
        "CREATE INDEX idx_sales_customer ON sales(CustomerKey)",
        "CREATE INDEX idx_sales_product ON sales(ProductKey)",
        "CREATE INDEX idx_sales_territory ON sales(TerritoryKey)",
        "CREATE INDEX idx_sales_order_number ON sales(OrderNumber)",
        "CREATE INDEX idx_returns_date ON returns(ReturnDate)",
        "CREATE INDEX idx_returns_product ON returns(ProductKey)",
        "CREATE INDEX idx_returns_territory ON returns(TerritoryKey)",
        "CREATE INDEX idx_products_subcategory ON products(ProductSubcategoryKey)",
    ]
    for statement in indexes:
        conn.execute(statement)


def create_analysis_views(conn: sqlite3.Connection) -> None:
    """Create reusable reporting views; views do not duplicate stored data."""
    conn.executescript(
        """
        -- One row per sales line, enriched with customer/product/territory data.
        CREATE VIEW sales_detail AS
        SELECT
            s.OrderDate,
            s.StockDate,
            s.OrderNumber,
            s.OrderLineItem,
            s.SalesYear,
            s.OrderQuantity,
            s.CustomerKey,
            TRIM(COALESCE(c.FirstName, '') || ' ' || COALESCE(c.LastName, '')) AS CustomerName,
            s.ProductKey,
            p.ProductName,
            p.ProductSKU,
            p.ProductPrice AS UnitListPrice,
            p.ProductCost AS UnitProductCost,
            p.ProductSubcategoryKey,
            ps.SubcategoryName,
            pc.ProductCategoryKey,
            pc.CategoryName,
            s.TerritoryKey,
            t.Region,
            t.Country,
            t.Continent,
            ROUND(s.OrderQuantity * COALESCE(p.ProductPrice, 0), 2) AS EstimatedRevenue,
            ROUND(s.OrderQuantity * COALESCE(p.ProductCost, 0), 2) AS EstimatedCOGS,
            ROUND(s.OrderQuantity * (COALESCE(p.ProductPrice, 0) - COALESCE(p.ProductCost, 0)), 2)
                AS EstimatedGrossProfit
        FROM sales s
        LEFT JOIN products p ON p.ProductKey = s.ProductKey
        LEFT JOIN customers c ON c.CustomerKey = s.CustomerKey
        LEFT JOIN product_subcategories ps ON ps.ProductSubcategoryKey = p.ProductSubcategoryKey
        LEFT JOIN product_categories pc ON pc.ProductCategoryKey = ps.ProductCategoryKey
        LEFT JOIN territories t ON t.SalesTerritoryKey = s.TerritoryKey;

        -- Customer-level purchasing metrics and customer profile attributes.
        CREATE VIEW customer_analysis AS
        WITH customer_sales AS (
            SELECT
                s.CustomerKey,
                COUNT(DISTINCT s.OrderNumber) AS TotalOrders,
                COUNT(*) AS TotalLineItems,
                SUM(s.OrderQuantity) AS TotalUnitsPurchased,
                ROUND(SUM(s.OrderQuantity * COALESCE(p.ProductPrice, 0)), 2) AS EstimatedRevenue,
                ROUND(SUM(s.OrderQuantity * COALESCE(p.ProductCost, 0)), 2) AS EstimatedCOGS,
                ROUND(SUM(s.OrderQuantity * (COALESCE(p.ProductPrice, 0) - COALESCE(p.ProductCost, 0))), 2)
                    AS EstimatedGrossProfit,
                MIN(s.OrderDate) AS FirstOrderDate,
                MAX(s.OrderDate) AS LastOrderDate
            FROM sales s
            JOIN products p ON p.ProductKey = s.ProductKey
            GROUP BY s.CustomerKey
        )
        SELECT
            c.CustomerKey,
            TRIM(COALESCE(c.FirstName, '') || ' ' || COALESCE(c.LastName, '')) AS CustomerName,
            c.Prefix,
            c.BirthDate,
            c.MaritalStatus,
            c.Gender,
            c.EmailAddress,
            c.AnnualIncome,
            c.TotalChildren,
            c.EducationLevel,
            c.Occupation,
            c.HomeOwner,
            COALESCE(cs.TotalOrders, 0) AS TotalOrders,
            COALESCE(cs.TotalLineItems, 0) AS TotalLineItems,
            COALESCE(cs.TotalUnitsPurchased, 0) AS TotalUnitsPurchased,
            COALESCE(cs.EstimatedRevenue, 0) AS EstimatedRevenue,
            COALESCE(cs.EstimatedCOGS, 0) AS EstimatedCOGS,
            COALESCE(cs.EstimatedGrossProfit, 0) AS EstimatedGrossProfit,
            CASE WHEN COALESCE(cs.TotalOrders, 0) = 0 THEN 0
                 ELSE ROUND(cs.EstimatedRevenue / cs.TotalOrders, 2) END AS AverageOrderValue,
            cs.FirstOrderDate,
            cs.LastOrderDate
        FROM customers c
        LEFT JOIN customer_sales cs ON cs.CustomerKey = c.CustomerKey;

        -- Product-level sales, margin, and returns metrics.
        CREATE VIEW product_analysis AS
        WITH sales_metrics AS (
            SELECT
                ProductKey,
                COUNT(*) AS SalesLineItems,
                COUNT(DISTINCT OrderNumber) AS TotalOrders,
                SUM(OrderQuantity) AS UnitsSold,
                ROUND(SUM(OrderQuantity * COALESCE(ProductPrice, 0)), 2) AS EstimatedRevenue,
                ROUND(SUM(OrderQuantity * COALESCE(ProductCost, 0)), 2) AS EstimatedCOGS,
                ROUND(SUM(OrderQuantity * (COALESCE(ProductPrice, 0) - COALESCE(ProductCost, 0))), 2)
                    AS EstimatedGrossProfit
            FROM sales s
            JOIN products p USING (ProductKey)
            GROUP BY ProductKey
        ), return_metrics AS (
            SELECT
                ProductKey,
                SUM(ReturnQuantity) AS UnitsReturned,
                ROUND(SUM(ReturnQuantity * COALESCE(ProductPrice, 0)), 2) AS EstimatedReturnValue,
                ROUND(SUM(ReturnQuantity * COALESCE(ProductCost, 0)), 2) AS EstimatedReturnCOGS
            FROM returns r
            JOIN products p USING (ProductKey)
            GROUP BY ProductKey
        )
        SELECT
            p.ProductKey,
            p.ProductSKU,
            p.ProductName,
            p.ModelName,
            p.ProductSubcategoryKey,
            p.ProductColor,
            p.ProductSize,
            p.ProductCost,
            p.ProductPrice,
            ps.SubcategoryName,
            pc.CategoryName,
            COALESCE(sm.SalesLineItems, 0) AS SalesLineItems,
            COALESCE(sm.TotalOrders, 0) AS TotalOrders,
            COALESCE(sm.UnitsSold, 0) AS UnitsSold,
            COALESCE(sm.EstimatedRevenue, 0) AS EstimatedRevenue,
            COALESCE(sm.EstimatedCOGS, 0) AS EstimatedCOGS,
            COALESCE(sm.EstimatedGrossProfit, 0) AS EstimatedGrossProfit,
            CASE WHEN COALESCE(sm.EstimatedRevenue, 0) = 0 THEN 0
                 ELSE ROUND(100.0 * sm.EstimatedGrossProfit / sm.EstimatedRevenue, 2) END AS GrossMarginPercent,
            COALESCE(rm.UnitsReturned, 0) AS UnitsReturned,
            COALESCE(rm.EstimatedReturnValue, 0) AS EstimatedReturnValue,
            COALESCE(rm.EstimatedReturnCOGS, 0) AS EstimatedReturnCOGS,
            CASE WHEN COALESCE(sm.UnitsSold, 0) = 0 THEN NULL
                 ELSE ROUND(100.0 * COALESCE(rm.UnitsReturned, 0) / sm.UnitsSold, 2) END AS ReturnRatePercent,
            ROUND(COALESCE(sm.EstimatedRevenue, 0) - COALESCE(rm.EstimatedReturnValue, 0), 2)
                AS EstimatedNetRevenueAfterReturns,
            ROUND(COALESCE(sm.EstimatedCOGS, 0) - COALESCE(rm.EstimatedReturnCOGS, 0), 2)
                AS EstimatedNetCOGSAfterReturns,
            ROUND(COALESCE(sm.EstimatedGrossProfit, 0)
                  - (COALESCE(rm.EstimatedReturnValue, 0) - COALESCE(rm.EstimatedReturnCOGS, 0)), 2)
                AS EstimatedGrossProfitAfterReturns
        FROM products p
        LEFT JOIN product_subcategories ps ON ps.ProductSubcategoryKey = p.ProductSubcategoryKey
        LEFT JOIN product_categories pc ON pc.ProductCategoryKey = ps.ProductCategoryKey
        LEFT JOIN sales_metrics sm ON sm.ProductKey = p.ProductKey
        LEFT JOIN return_metrics rm ON rm.ProductKey = p.ProductKey;

        CREATE VIEW category_analysis AS
        SELECT
            pc.ProductCategoryKey,
            pc.CategoryName,
            COUNT(pa.ProductKey) AS ProductCount,
            SUM(pa.UnitsSold) AS UnitsSold,
            SUM(pa.TotalOrders) AS ProductOrderCounts,
            ROUND(SUM(pa.EstimatedRevenue), 2) AS EstimatedRevenue,
            ROUND(SUM(pa.EstimatedCOGS), 2) AS EstimatedCOGS,
            ROUND(SUM(pa.EstimatedGrossProfit), 2) AS EstimatedGrossProfit,
            CASE WHEN SUM(pa.EstimatedRevenue) = 0 THEN 0
                 ELSE ROUND(100.0 * SUM(pa.EstimatedGrossProfit) / SUM(pa.EstimatedRevenue), 2) END
                AS GrossMarginPercent,
            SUM(pa.UnitsReturned) AS UnitsReturned,
            ROUND(SUM(pa.EstimatedReturnValue), 2) AS EstimatedReturnValue,
            ROUND(SUM(pa.EstimatedNetRevenueAfterReturns), 2) AS EstimatedNetRevenueAfterReturns,
            ROUND(SUM(pa.EstimatedGrossProfitAfterReturns), 2) AS EstimatedGrossProfitAfterReturns
        FROM product_categories pc
        LEFT JOIN product_subcategories ps USING (ProductCategoryKey)
        LEFT JOIN product_analysis pa USING (ProductSubcategoryKey)
        GROUP BY pc.ProductCategoryKey, pc.CategoryName;

        -- Sales and estimated return impact by sales territory.
        CREATE VIEW territory_analysis AS
        WITH sales_metrics AS (
            SELECT
                s.TerritoryKey,
                COUNT(DISTINCT s.OrderNumber) AS TotalOrders,
                SUM(s.OrderQuantity) AS UnitsSold,
                ROUND(SUM(s.OrderQuantity * p.ProductPrice), 2) AS EstimatedRevenue,
                ROUND(SUM(s.OrderQuantity * p.ProductCost), 2) AS EstimatedCOGS,
                ROUND(SUM(s.OrderQuantity * (p.ProductPrice - p.ProductCost)), 2) AS EstimatedGrossProfit
            FROM sales s JOIN products p USING (ProductKey)
            GROUP BY s.TerritoryKey
        ), return_metrics AS (
            SELECT
                r.TerritoryKey,
                SUM(r.ReturnQuantity) AS UnitsReturned,
                ROUND(SUM(r.ReturnQuantity * p.ProductPrice), 2) AS EstimatedReturnValue,
                ROUND(SUM(r.ReturnQuantity * p.ProductCost), 2) AS EstimatedReturnCOGS
            FROM returns r JOIN products p USING (ProductKey)
            GROUP BY r.TerritoryKey
        )
        SELECT
            t.SalesTerritoryKey AS TerritoryKey,
            t.Region,
            t.Country,
            t.Continent,
            COALESCE(sm.TotalOrders, 0) AS TotalOrders,
            COALESCE(sm.UnitsSold, 0) AS UnitsSold,
            COALESCE(sm.EstimatedRevenue, 0) AS EstimatedRevenue,
            COALESCE(sm.EstimatedCOGS, 0) AS EstimatedCOGS,
            COALESCE(sm.EstimatedGrossProfit, 0) AS EstimatedGrossProfit,
            CASE WHEN COALESCE(sm.EstimatedRevenue, 0) = 0 THEN 0
                 ELSE ROUND(100.0 * sm.EstimatedGrossProfit / sm.EstimatedRevenue, 2) END AS GrossMarginPercent,
            COALESCE(rm.UnitsReturned, 0) AS UnitsReturned,
            COALESCE(rm.EstimatedReturnValue, 0) AS EstimatedReturnValue,
            ROUND(COALESCE(sm.EstimatedRevenue, 0) - COALESCE(rm.EstimatedReturnValue, 0), 2)
                AS EstimatedNetRevenueAfterReturns,
            ROUND(COALESCE(sm.EstimatedGrossProfit, 0)
                  - (COALESCE(rm.EstimatedReturnValue, 0) - COALESCE(rm.EstimatedReturnCOGS, 0)), 2)
                AS EstimatedGrossProfitAfterReturns
        FROM territories t
        LEFT JOIN sales_metrics sm ON sm.TerritoryKey = t.SalesTerritoryKey
        LEFT JOIN return_metrics rm ON rm.TerritoryKey = t.SalesTerritoryKey;

        CREATE VIEW order_analysis AS
        SELECT
            s.OrderNumber,
            MIN(s.OrderDate) AS OrderDate,
            MIN(s.CustomerKey) AS CustomerKey,
            TRIM(COALESCE(MIN(c.FirstName), '') || ' ' || COALESCE(MIN(c.LastName), '')) AS CustomerName,
            MIN(s.TerritoryKey) AS TerritoryKey,
            MIN(t.Region) AS Region,
            COUNT(*) AS LineItems,
            SUM(s.OrderQuantity) AS TotalUnits,
            ROUND(SUM(s.OrderQuantity * p.ProductPrice), 2) AS EstimatedRevenue,
            ROUND(SUM(s.OrderQuantity * p.ProductCost), 2) AS EstimatedCOGS,
            ROUND(SUM(s.OrderQuantity * (p.ProductPrice - p.ProductCost)), 2) AS EstimatedGrossProfit
        FROM sales s
        JOIN products p USING (ProductKey)
        LEFT JOIN customers c ON c.CustomerKey = s.CustomerKey
        LEFT JOIN territories t ON t.SalesTerritoryKey = s.TerritoryKey
        GROUP BY s.OrderNumber;

        CREATE VIEW return_analysis AS
        SELECT
            r.ReturnID,
            r.ReturnDate,
            r.TerritoryKey,
            t.Region,
            t.Country,
            r.ProductKey,
            p.ProductName,
            ps.SubcategoryName,
            pc.CategoryName,
            r.ReturnQuantity,
            ROUND(r.ReturnQuantity * p.ProductPrice, 2) AS EstimatedReturnValue,
            ROUND(r.ReturnQuantity * p.ProductCost, 2) AS EstimatedReturnCOGS
        FROM returns r
        JOIN products p USING (ProductKey)
        LEFT JOIN product_subcategories ps ON ps.ProductSubcategoryKey = p.ProductSubcategoryKey
        LEFT JOIN product_categories pc ON pc.ProductCategoryKey = ps.ProductCategoryKey
        LEFT JOIN territories t ON t.SalesTerritoryKey = r.TerritoryKey;

        CREATE VIEW monthly_profit_analysis AS
        WITH sales_monthly AS (
            SELECT
                CAST(strftime('%Y', s.OrderDate) AS INTEGER) AS Year,
                CAST(strftime('%m', s.OrderDate) AS INTEGER) AS Month,
                SUM(s.OrderQuantity) AS UnitsSold,
                COUNT(DISTINCT s.OrderNumber) AS TotalOrders,
                ROUND(SUM(s.OrderQuantity * p.ProductPrice), 2) AS EstimatedRevenue,
                ROUND(SUM(s.OrderQuantity * p.ProductCost), 2) AS EstimatedCOGS,
                ROUND(SUM(s.OrderQuantity * (p.ProductPrice - p.ProductCost)), 2) AS EstimatedGrossProfit
            FROM sales s JOIN products p USING (ProductKey)
            GROUP BY Year, Month
        ), returns_monthly AS (
            SELECT
                CAST(strftime('%Y', r.ReturnDate) AS INTEGER) AS Year,
                CAST(strftime('%m', r.ReturnDate) AS INTEGER) AS Month,
                SUM(r.ReturnQuantity) AS UnitsReturned,
                ROUND(SUM(r.ReturnQuantity * p.ProductPrice), 2) AS EstimatedReturnValue,
                ROUND(SUM(r.ReturnQuantity * p.ProductCost), 2) AS EstimatedReturnCOGS
            FROM returns r JOIN products p USING (ProductKey)
            GROUP BY Year, Month
        ), periods AS (
            SELECT Year, Month FROM sales_monthly
            UNION
            SELECT Year, Month FROM returns_monthly
        )
        SELECT
            periods.Year,
            periods.Month,
            printf('%04d-%02d', periods.Year, periods.Month) AS YearMonth,
            COALESCE(sm.TotalOrders, 0) AS TotalOrders,
            COALESCE(sm.UnitsSold, 0) AS UnitsSold,
            COALESCE(sm.EstimatedRevenue, 0) AS EstimatedRevenue,
            COALESCE(sm.EstimatedCOGS, 0) AS EstimatedCOGS,
            COALESCE(sm.EstimatedGrossProfit, 0) AS EstimatedGrossProfit,
            COALESCE(rm.UnitsReturned, 0) AS UnitsReturned,
            COALESCE(rm.EstimatedReturnValue, 0) AS EstimatedReturnValue,
            ROUND(COALESCE(sm.EstimatedRevenue, 0) - COALESCE(rm.EstimatedReturnValue, 0), 2)
                AS EstimatedNetRevenueAfterReturns,
            ROUND(COALESCE(sm.EstimatedGrossProfit, 0)
                  - (COALESCE(rm.EstimatedReturnValue, 0) - COALESCE(rm.EstimatedReturnCOGS, 0)), 2)
                AS EstimatedGrossProfitAfterReturns
        FROM periods
        LEFT JOIN sales_monthly sm USING (Year, Month)
        LEFT JOIN returns_monthly rm USING (Year, Month);

        CREATE VIEW annual_profit_analysis AS
        WITH sales_yearly AS (
            SELECT
                s.SalesYear AS Year,
                SUM(s.OrderQuantity) AS UnitsSold,
                COUNT(DISTINCT s.OrderNumber) AS TotalOrders,
                ROUND(SUM(s.OrderQuantity * p.ProductPrice), 2) AS EstimatedRevenue,
                ROUND(SUM(s.OrderQuantity * p.ProductCost), 2) AS EstimatedCOGS,
                ROUND(SUM(s.OrderQuantity * (p.ProductPrice - p.ProductCost)), 2) AS EstimatedGrossProfit
            FROM sales s JOIN products p USING (ProductKey)
            GROUP BY s.SalesYear
        ), returns_yearly AS (
            SELECT
                CAST(strftime('%Y', r.ReturnDate) AS INTEGER) AS Year,
                SUM(r.ReturnQuantity) AS UnitsReturned,
                ROUND(SUM(r.ReturnQuantity * p.ProductPrice), 2) AS EstimatedReturnValue,
                ROUND(SUM(r.ReturnQuantity * p.ProductCost), 2) AS EstimatedReturnCOGS
            FROM returns r JOIN products p USING (ProductKey)
            GROUP BY Year
        ), years AS (
            SELECT Year FROM sales_yearly
            UNION
            SELECT Year FROM returns_yearly
        )
        SELECT
            years.Year,
            COALESCE(sy.TotalOrders, 0) AS TotalOrders,
            COALESCE(sy.UnitsSold, 0) AS UnitsSold,
            COALESCE(sy.EstimatedRevenue, 0) AS EstimatedRevenue,
            COALESCE(sy.EstimatedCOGS, 0) AS EstimatedCOGS,
            COALESCE(sy.EstimatedGrossProfit, 0) AS EstimatedGrossProfit,
            COALESCE(ry.UnitsReturned, 0) AS UnitsReturned,
            COALESCE(ry.EstimatedReturnValue, 0) AS EstimatedReturnValue,
            ROUND(COALESCE(sy.EstimatedRevenue, 0) - COALESCE(ry.EstimatedReturnValue, 0), 2)
                AS EstimatedNetRevenueAfterReturns,
            ROUND(COALESCE(sy.EstimatedGrossProfit, 0)
                  - (COALESCE(ry.EstimatedReturnValue, 0) - COALESCE(ry.EstimatedReturnCOGS, 0)), 2)
                AS EstimatedGrossProfitAfterReturns
        FROM years
        LEFT JOIN sales_yearly sy USING (Year)
        LEFT JOIN returns_yearly ry USING (Year);

        CREATE VIEW company_profit_analysis AS
        WITH sales_total AS (
            SELECT
                COUNT(DISTINCT s.OrderNumber) AS TotalOrders,
                COUNT(*) AS TotalSalesLineItems,
                SUM(s.OrderQuantity) AS UnitsSold,
                ROUND(SUM(s.OrderQuantity * p.ProductPrice), 2) AS EstimatedRevenue,
                ROUND(SUM(s.OrderQuantity * p.ProductCost), 2) AS EstimatedCOGS,
                ROUND(SUM(s.OrderQuantity * (p.ProductPrice - p.ProductCost)), 2) AS EstimatedGrossProfit
            FROM sales s JOIN products p USING (ProductKey)
        ), return_total AS (
            SELECT
                SUM(r.ReturnQuantity) AS UnitsReturned,
                ROUND(SUM(r.ReturnQuantity * p.ProductPrice), 2) AS EstimatedReturnValue,
                ROUND(SUM(r.ReturnQuantity * p.ProductCost), 2) AS EstimatedReturnCOGS
            FROM returns r JOIN products p USING (ProductKey)
        )
        SELECT
            st.TotalOrders,
            st.TotalSalesLineItems,
            st.UnitsSold,
            st.EstimatedRevenue,
            st.EstimatedCOGS,
            st.EstimatedGrossProfit,
            CASE WHEN st.EstimatedRevenue = 0 THEN 0
                 ELSE ROUND(100.0 * st.EstimatedGrossProfit / st.EstimatedRevenue, 2) END AS GrossMarginPercent,
            COALESCE(rt.UnitsReturned, 0) AS UnitsReturned,
            COALESCE(rt.EstimatedReturnValue, 0) AS EstimatedReturnValue,
            ROUND(st.EstimatedRevenue - COALESCE(rt.EstimatedReturnValue, 0), 2)
                AS EstimatedNetRevenueAfterReturns,
            ROUND(st.EstimatedCOGS - COALESCE(rt.EstimatedReturnCOGS, 0), 2)
                AS EstimatedNetCOGSAfterReturns,
            ROUND(st.EstimatedGrossProfit
                  - (COALESCE(rt.EstimatedReturnValue, 0) - COALESCE(rt.EstimatedReturnCOGS, 0)), 2)
                AS EstimatedGrossProfitAfterReturns,
            CASE WHEN st.EstimatedRevenue = 0 THEN 0
                 ELSE ROUND(100.0 * (
                     st.EstimatedGrossProfit
                     - (COALESCE(rt.EstimatedReturnValue, 0) - COALESCE(rt.EstimatedReturnCOGS, 0))
                 ) / NULLIF(st.EstimatedRevenue - COALESCE(rt.EstimatedReturnValue, 0), 0), 2)
            END AS EstimatedGrossMarginAfterReturnsPercent
        FROM sales_total st CROSS JOIN return_total rt;
        """
    )


def validate_foreign_keys(conn: sqlite3.Connection) -> None:
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        sample = violations[:10]
        raise ValueError(f"Foreign-key validation failed. First violations: {sample}")


def print_database_summary(conn: sqlite3.Connection, db_path: Path) -> None:
    print(f"\nDatabase created: {db_path.resolve()}")
    print("\nStored tables:")
    for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ):
        count = conn.execute(f'SELECT COUNT(*) FROM "{row[0]}"').fetchone()[0]
        print(f"  {row[0]:28} {count:>10,} rows")

    print("\nAnalysis views:")
    for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='view' ORDER BY name"
    ):
        print(f"  {row[0]}")

    print("\nCompany-wide estimated performance:")
    result = conn.execute("SELECT * FROM company_profit_analysis").fetchone()
    columns = [item[0] for item in conn.execute("SELECT * FROM company_profit_analysis").description]
    for name, value in zip(columns, result):
        print(f"  {name:36} {value}")

    print("\nAnnual estimated performance:")
    annual = pd.read_sql_query(
        "SELECT * FROM annual_profit_analysis ORDER BY Year", conn
    )
    print(annual.to_string(index=False))


def build_database(zip_path: Path | None, data_dir: Path, db_path: Path) -> None:
    if zip_path is not None and not zip_path.exists():
        raise FileNotFoundError(f"ZIP archive not found: {zip_path}")

    archive_context: zipfile.ZipFile | None = None
    try:
        if zip_path is not None:
            archive_context = zipfile.ZipFile(zip_path, "r")

        data = load_source_data(archive_context, data_dir)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA foreign_keys = OFF")
            create_schema(conn)

            for table_name, dataframe in data.items():
                dataframe.to_sql(table_name, conn, if_exists="append", index=False)
                print(f"Loaded {table_name:24} {len(dataframe):>10,} rows")

            conn.execute("PRAGMA foreign_keys = ON")
            validate_foreign_keys(conn)
            create_indexes(conn)
            create_analysis_views(conn)
            conn.commit()
            print_database_summary(conn, db_path)

        print("\nDone. Open company.db with SQLite Browser or query it with Python/SQL.")
    finally:
        if archive_context is not None:
            archive_context.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create an analysis-ready AdventureWorks SQLite database.")
    parser.add_argument(
        "--zip",
        dest="zip_path",
        default="archive (4).zip",
        help="Path to the ZIP containing AdventureWorks CSVs (default: archive (4).zip).",
    )
    parser.add_argument(
        "--data-dir",
        default=".",
        help="Directory containing extracted CSVs; used when --zip is set to an empty string.",
    )
    parser.add_argument("--db", default="company.db", help="Output SQLite database path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    zip_path = Path(args.zip_path) if args.zip_path else None
    build_database(zip_path, Path(args.data_dir), Path(args.db))


if __name__ == "__main__":
    main()
