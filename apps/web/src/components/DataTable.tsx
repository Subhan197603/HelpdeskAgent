import type { ReactNode } from "react";

export interface DataColumn<Row> {
  header: string;
  key: string;
  render: (row: Row) => ReactNode;
}

export function DataTable<Row>({
  caption,
  columns,
  empty,
  getRowKey,
  rows,
}: {
  caption: string;
  columns: readonly DataColumn<Row>[];
  empty?: ReactNode;
  getRowKey: (row: Row) => string;
  rows: readonly Row[];
}) {
  if (rows.length === 0) return <>{empty}</>;
  return (
    <div className="data-table-wrap">
      <table className="data-table">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key} scope="col">
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={getRowKey(row)}>
              {columns.map((column) => (
                <td key={column.key} data-label={column.header}>
                  {column.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function TableToolbar({
  children,
  label = "Table controls",
}: {
  children: ReactNode;
  label?: string;
}) {
  return (
    <div aria-label={label} className="table-toolbar" role="group">
      {children}
    </div>
  );
}

export function FilterChips({
  filters,
  onRemove,
}: {
  filters: readonly string[];
  onRemove?: (filter: string) => void;
}) {
  return (
    <div aria-label="Active filters" className="filter-chips">
      {filters.map((filter) => (
        <span key={filter}>
          {filter}
          {onRemove && (
            <button
              aria-label={`Remove ${filter} filter`}
              onClick={() => {
                onRemove(filter);
              }}
              type="button"
            >
              ×
            </button>
          )}
        </span>
      ))}
    </div>
  );
}

export function Pagination({
  hasNext,
  onNext,
  onPrevious,
  page,
}: {
  hasNext: boolean;
  onNext: () => void;
  onPrevious: () => void;
  page: number;
}) {
  return (
    <nav aria-label="Pagination" className="pagination">
      <button disabled={page <= 1} onClick={onPrevious} type="button">
        Previous
      </button>
      <span aria-current="page">Page {page}</span>
      <button disabled={!hasNext} onClick={onNext} type="button">
        Next
      </button>
    </nav>
  );
}

export function SortControl({
  label,
  onChange,
  options,
  value,
}: {
  label: string;
  onChange: (value: string) => void;
  options: readonly { label: string; value: string }[];
  value: string;
}) {
  return (
    <label className="sort-control">
      {label}
      <select
        onChange={(event) => {
          onChange(event.target.value);
        }}
        value={value}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}
