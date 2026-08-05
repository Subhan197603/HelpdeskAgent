import { Link } from "react-router-dom";

export function formatDelta(current: number, previous: number): string {
  if (previous > 0) {
    const percent = Math.round(((current - previous) / previous) * 100);
    return `${percent > 0 ? "+" : ""}${String(percent)}% from yesterday`;
  }
  if (current > 0) return `+${String(current)} — no prior comparison`;
  return "No prior comparison";
}

export interface DonutSlice {
  label: string;
  value: number;
}

const CIRCUMFERENCE = 100;

export function DonutChart({
  centerText,
  label,
  slices,
}: {
  centerText?: string;
  label: string;
  slices: readonly DonutSlice[];
}) {
  const visible = slices.filter((slice) => slice.value > 0);
  const total = visible.reduce((sum, slice) => sum + slice.value, 0);
  if (total === 0) {
    return (
      <p className="donut-empty">
        No data yet. Values appear as tickets are worked.
      </p>
    );
  }
  const summary = visible
    .map(
      (slice) =>
        `${slice.label} ${String(slice.value)} (${String(Math.round((slice.value / total) * 100))}%)`,
    )
    .join(", ");
  let offset = 25;
  return (
    <div className="donut">
      <svg
        aria-label={`${label}: ${summary}`}
        className="donut__chart"
        role="img"
        viewBox="0 0 42 42"
      >
        {visible.map((slice, index) => {
          const share = (slice.value / total) * CIRCUMFERENCE;
          const circle = (
            <circle
              className={`donut__slice donut__slice--${String(index % 5)}`}
              cx="21"
              cy="21"
              fill="transparent"
              key={slice.label}
              r="15.9155"
              strokeDasharray={`${String(share)} ${String(CIRCUMFERENCE - share)}`}
              strokeDashoffset={String(offset)}
            />
          );
          offset -= share;
          return circle;
        })}
        {centerText !== undefined && (
          <text className="donut__center" textAnchor="middle" x="21" y="23">
            {centerText}
          </text>
        )}
      </svg>
      <ul className="donut-legend">
        {visible.map((slice, index) => (
          <li key={slice.label}>
            <span
              aria-hidden="true"
              className={`donut-legend__swatch donut-legend__swatch--${String(index % 5)}`}
            />
            {slice.label}
            <strong>{slice.value}</strong>
            <small>{Math.round((slice.value / total) * 100)}%</small>
          </li>
        ))}
      </ul>
      <table className="sr-only">
        <caption>{label}</caption>
        <thead>
          <tr>
            <th scope="col">Category</th>
            <th scope="col">Count</th>
            <th scope="col">Share</th>
          </tr>
        </thead>
        <tbody>
          {visible.map((slice) => (
            <tr key={slice.label}>
              <th scope="row">{slice.label}</th>
              <td>{slice.value}</td>
              <td>{Math.round((slice.value / total) * 100)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export interface DashboardActivityItem {
  actor_name: string | null;
  created_at: string;
  event_type: string;
  id: string;
  ticket_key: string;
}

function eventText(eventType: string): string {
  return eventType.replaceAll("_", " ").toLowerCase();
}

export function ActivityFeed({
  items,
}: {
  items: readonly DashboardActivityItem[];
}) {
  if (items.length === 0)
    return <p className="donut-empty">No recent activity.</p>;
  return (
    <ol className="activity-feed">
      {items.map((item) => (
        <li key={item.id}>
          <div>
            <Link to={`/agent/tickets/${item.ticket_key}`}>
              {item.ticket_key}
            </Link>{" "}
            {eventText(item.event_type)}
            {item.actor_name ? ` — ${item.actor_name}` : ""}
          </div>
          <time dateTime={item.created_at}>
            {new Date(item.created_at).toLocaleString()}
          </time>
        </li>
      ))}
    </ol>
  );
}
