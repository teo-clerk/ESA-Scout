/**
 * TypeScript mirror of the Python models in `agent/models.py`.
 *
 * This is the on-disk contract for `data/opportunities.json`. When you change a
 * field here, change `agent/models.py` to match — the Python `to_dict` methods
 * are the source of truth.
 */

export type Status = "Open" | "Pending" | "Closed" | "Unknown";

export const STATUSES: Status[] = ["Open", "Pending", "Closed", "Unknown"];

export interface ChecklistItem {
  task: string;
  effort: string;
  done_when: string;
}

export interface KeyDeadline {
  label: string;
  date: string;
}

export interface Evaluation {
  match_score: number;
  justification: string;
  why_apply: string[];
  required_skills: string[];
  gaps: string[];
  checklist: ChecklistItem[];
  key_deadlines: KeyDeadline[];
  model: string;
  evaluated_at: string;
  fingerprint: string;
  error: string;
}

export interface Opportunity {
  id: string;
  title: string;
  source: string;
  source_label: string;
  url: string;
  status: Status;
  kind: string;
  category: string;
  location: string;
  summary: string;
  activity_dates: string;
  /** ISO date, or "" when unknown. */
  activity_start: string;
  deadline_text: string;
  /** ISO date, or "" when unknown. */
  deadline: string;
  first_seen: string;
  last_seen: string;
  content_hash: string;
  match_score: number;
  evaluation: Evaluation | null;
}

export interface Repository {
  name: string;
  description: string;
  language: string;
  url: string;
  stars: number;
  topics: string[];
  pushed_at: string;
}

export interface GitHubProfile {
  username: string;
  profile_url: string;
  repos: Repository[];
  languages: string[];
  error: string;
}

export interface Profile {
  name: string;
  headline: string;
  source_file: string;
  education: string[];
  skills: string[];
  highlights: string[];
  github: GitHubProfile;
  fingerprint: string;
  error: string;
}

export interface Stats {
  total: number;
  open: number;
  pending: number;
  closed: number;
  high_fit: number;
  evaluated: number;
}

export interface ChangeEventRecord {
  kind: string;
  opportunity_id: string;
  title: string;
  status: string;
  previous_status: string;
  match_score: number;
  url: string;
  detail: string;
}

export interface Snapshot {
  version: number;
  generated_at: string;
  stats: Stats;
  profile: Profile;
  opportunities: Opportunity[];
  events: ChangeEventRecord[];
  errors: string[];
}

/** Shown before the agent has ever run, so the dashboard renders regardless. */
export const EMPTY_SNAPSHOT: Snapshot = {
  version: 1,
  generated_at: "",
  stats: { total: 0, open: 0, pending: 0, closed: 0, high_fit: 0, evaluated: 0 },
  profile: {
    name: "",
    headline: "",
    source_file: "",
    education: [],
    skills: [],
    highlights: [],
    github: {
      username: "",
      profile_url: "",
      repos: [],
      languages: [],
      error: "",
    },
    fingerprint: "",
    error: "",
  },
  opportunities: [],
  events: [],
  errors: [],
};

export type SortKey = "match" | "deadline" | "title";
export type StatusFilter = Status | "All";
