"use client";

import React, {
    useState,
    useCallback,
    useRef,
    useEffect,
    type DragEvent as ReactDragEvent,
} from "react";
import { toast, Toaster } from "react-hot-toast";

// ─── Types ───────────────────────────────────────────────

interface StrategyCondition {
    indicator?: string;
    params?: number[];
    crossover?: boolean;
    crossunder?: boolean;
    operator?: string;
    threshold?: number;
    field?: string;
    timeframe?: string;
    value?: string;
    bars?: number;
    compare_to?: string;
    compare_params?: number[];
}

interface RiskModifiers {
    stop_loss_percent?: number;
    take_profit_percent?: number;
    trailing_stop_percent?: number;
    max_holding_bars?: number;
}

interface StrategyDefinition {
    name: string;
    description?: string;
    conditions: StrategyCondition[];
    action: string;
    quantity_percent?: number;
    cooldown_bars?: number;
    risk_modifiers?: RiskModifiers;
    symbols: string[];
    timeframe?: string;
    tags?: string[];
}

interface Strategy {
    id: number;
    user_id: number;
    name: string;
    description: string | null;
    json_definition: StrategyDefinition;
    is_active: boolean;
    version: number;
    tags: string[] | null;
    created_at: string;
    updated_at: string;
}

interface ValidateResponse {
    valid: boolean;
    errors: string[];
    strategy_name: string;
    indicators_used: string[];
    symbols: string[];
}

// ─── Default template ──────────────────────────────────

const DEFAULT_TEMPLATE: StrategyDefinition = {
    name: "My Strategy",
    conditions: [
        {
            indicator: "EMA",
            params: [9, 21],
            crossover: true,
        },
        {
            indicator: "RSI",
            params: [14],
            operator: ">",
            threshold: 30,
        },
    ],
    action: "buy",
    quantity_percent: 20,
    cooldown_bars: 5,
    symbols: ["BTC/USDT"],
    timeframe: "1h",
    tags: ["trend-following"],
    risk_modifiers: {
        stop_loss_percent: 5,
        take_profit_percent: 10,
    },
};

// ─── Helpers ───────────────────────────────────────────

import api from "@/lib/api";

function formatJson(obj: unknown): string {
    return JSON.stringify(obj, null, 2);
}

// ─── Components ────────────────────────────────────────

function Navbar() {
    return (
        <nav className="border-b border-slate-700 bg-slate-900 px-6 py-3 flex items-center justify-between">
            <div className="flex items-center gap-3">
                <span className="text-xl font-bold text-white tracking-tight">
                    ⚡ Trading Dashboard
                </span>
            </div>
            <div className="flex items-center gap-4 text-sm text-slate-300">
                <a href="/strategies" className="hover:text-white transition">
                    Strategies
                </a>
            </div>
        </nav>
    );
}

// ─── JSON Editor (Textarea with line numbers) ──────────

function JsonEditor({
    value,
    onChange,
    readOnly = false,
}: {
    value: string;
    onChange?: (v: string) => void;
    readOnly?: boolean;
}) {
    const lines = value.split("\n");
    return (
        <div className="flex font-mono text-sm border border-slate-600 rounded-lg overflow-hidden bg-slate-900">
            <div className="py-3 px-3 bg-slate-800 text-slate-500 select-none text-right border-r border-slate-700 leading-6">
                {lines.map((_, i) => (
                    <div key={i}>{i + 1}</div>
                ))}
            </div>
            <textarea
                value={value}
                onChange={onChange ? (e) => onChange(e.target.value) : undefined}
                readOnly={readOnly}
                rows={Math.max(lines.length, 10)}
                spellCheck={false}
                className="w-full py-3 px-4 bg-transparent text-green-300 outline-none resize-none leading-6 placeholder-slate-600"
                placeholder='{"name": "My Strategy", ...}'
            />
        </div>
    );
}

// ─── Strategy Card ─────────────────────────────────────

function StrategyCard({
    strategy,
    onEdit,
    onDelete,
    onToggle,
}: {
    strategy: Strategy;
    onEdit: () => void;
    onDelete: () => void;
    onToggle: () => void;
}) {
    const def = strategy.json_definition;
    const isActive = strategy.is_active;
    return (
        <div className="border border-slate-700 rounded-xl p-5 bg-slate-800/60 hover:border-slate-500 transition flex flex-col gap-3">
            <div className="flex items-start justify-between">
                <div>
                    <h3 className="text-lg font-semibold text-white">
                        {def.name}
                    </h3>
                    {strategy.description && (
                        <p className="text-sm text-slate-400 mt-0.5">
                            {strategy.description}
                        </p>
                    )}
                    <p className="text-xs text-slate-500 mt-1">
                        v{strategy.version} ·{" "}
                        {new Date(strategy.created_at).toLocaleDateString()}
                    </p>
                </div>
                <span
                    className={`px-2 py-0.5 text-xs rounded-full font-medium ${isActive
                        ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
                        : "bg-slate-700 text-slate-400"
                        }`}
                >
                    {isActive ? "Active" : "Paused"}
                </span>
            </div>

            <div className="flex flex-wrap gap-1.5">
                {def.symbols?.map((s: string) => (
                    <span
                        key={s}
                        className="px-2 py-0.5 rounded bg-indigo-500/15 text-indigo-300 text-xs font-medium"
                    >
                        {s}
                    </span>
                ))}
                <span className="px-2 py-0.5 rounded bg-amber-500/15 text-amber-300 text-xs font-medium uppercase">
                    {def.action}
                </span>
                <span className="px-2 py-0.5 rounded bg-slate-700 text-slate-300 text-xs">
                    {def.conditions?.length || 0} condition
                    {(def.conditions?.length || 0) !== 1 ? "s" : ""}
                </span>
                {def.timeframe && (
                    <span className="px-2 py-0.5 rounded bg-slate-700 text-slate-300 text-xs">
                        {def.timeframe}
                    </span>
                )}
            </div>

            <div className="flex flex-wrap gap-1.5">
                {def.tags?.map((t: string) => (
                    <span
                        key={t}
                        className="text-[11px] text-slate-500 bg-slate-700/50 px-1.5 py-0.5 rounded"
                    >
                        #{t}
                    </span>
                ))}
            </div>

            <div className="flex gap-2 mt-1">
                <button
                    onClick={onEdit}
                    className="text-xs px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-medium transition"
                >
                    Edit JSON
                </button>
                <button
                    onClick={onToggle}
                    className={`text-xs px-3 py-1.5 rounded-lg font-medium transition ${isActive
                        ? "bg-amber-600 hover:bg-amber-700 text-white"
                        : "bg-emerald-600 hover:bg-emerald-700 text-white"
                        }`}
                >
                    {isActive ? "Pause" : "Activate"}
                </button>
                <button
                    onClick={onDelete}
                    className="text-xs px-3 py-1.5 rounded-lg bg-red-600/60 hover:bg-red-700 text-white font-medium transition"
                >
                    Delete
                </button>
            </div>
        </div>
    );
}

// ─── Create / Edit Modal ──────────────────────────────

function StrategyModal({
    open,
    onClose,
    existing,
    onSaved,
}: {
    open: boolean;
    onClose: () => void;
    existing?: Strategy | null;
    onSaved: () => void;
}) {
    const [name, setName] = useState(existing?.name ?? "");
    const [description, setDescription] = useState(
        existing?.description ?? ""
    );
    const [jsonText, setJsonText] = useState(
        existing
            ? formatJson(existing.json_definition)
            : formatJson(DEFAULT_TEMPLATE)
    );
    const [isActive, setIsActive] = useState(existing?.is_active ?? false);
    const [tagsInput, setTagsInput] = useState(
        existing?.tags?.join(", ") ?? ""
    );
    const [validation, setValidation] = useState<ValidateResponse | null>(null);
    const [saving, setSaving] = useState(false);
    const [dragOver, setDragOver] = useState(false);

    useEffect(() => {
        if (existing) {
            setName(existing.name);
            setDescription(existing.description ?? "");
            setJsonText(formatJson(existing.json_definition));
            setIsActive(existing.is_active);
            setTagsInput(existing.tags?.join(", ") ?? "");
        } else {
            setName("My Strategy");
            setDescription("");
            setJsonText(formatJson(DEFAULT_TEMPLATE));
            setIsActive(false);
            setTagsInput("");
        }
        setValidation(null);
    }, [existing, open]);

    const handleDrop = useCallback((e: ReactDragEvent) => {
        e.preventDefault();
        setDragOver(false);
        const file = e.dataTransfer.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = (ev) => {
            const text = ev.target?.result;
            if (typeof text === "string") {
                setJsonText(text);
                toast.success("JSON file loaded");
            }
        };
        reader.readAsText(file);
    }, []);

    if (!open) return null;

    const handleValidate = async () => {
        try {
            let parsed: StrategyDefinition;
            try {
                parsed = JSON.parse(jsonText);
            } catch {
                setValidation({
                    valid: false,
                    errors: ["Invalid JSON: " + (jsonText ? "Check syntax" : "Empty body")],
                    strategy_name: "",
                    indicators_used: [],
                    symbols: [],
                });
                return;
            }
            const res = await api.post<ValidateResponse>(
                `/strategies/${existing?.id ?? "0"}/validate`,
                { json_definition: parsed }
            );
            setValidation(res.data);
            if (res.data.valid) toast.success("Strategy is valid!");
            else toast.error(`${res.data.errors.length} validation error(s)`);
        } catch {
            // Error toast already shown by interceptor
        }
    };

    const handleSave = async () => {
        let parsed: StrategyDefinition;
        try {
            parsed = JSON.parse(jsonText);
        } catch {
            toast.error("Invalid JSON before save");
            return;
        }
        setSaving(true);
        try {
            const tags = tagsInput
                .split(",")
                .map((t) => t.trim())
                .filter(Boolean);

            if (existing) {
                await api.put(`/strategies/${existing.id}`, {
                    name,
                    description: description || null,
                    json_definition: parsed,
                    is_active: isActive,
                    tags: tags.length > 0 ? tags : null,
                });
                toast.success("Strategy updated");
            } else {
                await api.post("/strategies/", {
                    name,
                    description: description || null,
                    json_definition: parsed,
                    is_active: isActive,
                    tags: tags.length > 0 ? tags : null,
                });
                toast.success("Strategy created");
            }
            onSaved();
            onClose();
        } catch {
            // Interceptor handles toast
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
            <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-4xl max-h-[90vh] overflow-y-auto mx-4 shadow-2xl">
                {/* Header */}
                <div className="sticky top-0 bg-slate-900 border-b border-slate-700 px-6 py-4 flex items-center justify-between rounded-t-2xl">
                    <h2 className="text-lg font-bold text-white">
                        {existing ? "Edit Strategy" : "New Strategy"}
                    </h2>
                    <button
                        onClick={onClose}
                        className="text-slate-400 hover:text-white text-2xl leading-none"
                    >
                        ✕
                    </button>
                </div>

                <div className="p-6 space-y-5">
                    {/* Name / Description */}
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                        <div>
                            <label className="block text-xs font-semibold text-slate-400 mb-1 uppercase tracking-wider">
                                Strategy Name
                            </label>
                            <input
                                value={name}
                                onChange={(e) => setName(e.target.value)}
                                className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                                placeholder="Cross EMA"
                            />
                        </div>
                        <div>
                            <label className="block text-xs font-semibold text-slate-400 mb-1 uppercase tracking-wider">
                                Tags (comma separated)
                            </label>
                            <input
                                value={tagsInput}
                                onChange={(e) => setTagsInput(e.target.value)}
                                className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                                placeholder="trend, breakout"
                            />
                        </div>
                    </div>

                    <div>
                        <label className="block text-xs font-semibold text-slate-400 mb-1 uppercase tracking-wider">
                            Description
                        </label>
                        <input
                            value={description}
                            onChange={(e) => setDescription(e.target.value)}
                            className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                            placeholder="Optional description..."
                        />
                    </div>

                    {/* Active toggle */}
                    <label className="flex items-center gap-3 cursor-pointer w-fit">
                        <div className="relative">
                            <input
                                type="checkbox"
                                checked={isActive}
                                onChange={(e) => setIsActive(e.target.checked)}
                                className="sr-only"
                            />
                            <div
                                className={`w-10 h-5 rounded-full transition ${isActive ? "bg-emerald-500" : "bg-slate-600"
                                    }`}
                            />
                            <div
                                className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform ${isActive ? "translate-x-5" : ""
                                    }`}
                            />
                        </div>
                        <span className="text-sm text-slate-300 font-medium">
                            Active
                        </span>
                    </label>

                    {/* JSON Editor with drag-drop */}
                    <div>
                        <label className="block text-xs font-semibold text-slate-400 mb-1 uppercase tracking-wider">
                            JSON Definition{" "}
                            <span className="text-slate-600 font-normal">
                                (drag & drop .json file)
                            </span>
                        </label>
                        <div
                            onDragOver={(e) => {
                                e.preventDefault();
                                setDragOver(true);
                            }}
                            onDragLeave={() => setDragOver(false)}
                            onDrop={handleDrop}
                            className={`rounded-lg transition ${dragOver
                                ? "ring-2 ring-indigo-400 ring-offset-2 ring-offset-slate-900"
                                : ""
                                }`}
                        >
                            <JsonEditor
                                value={jsonText}
                                onChange={setJsonText}
                            />
                        </div>
                    </div>

                    {/* Validation result */}
                    {validation && (
                        <div
                            className={`rounded-lg p-4 border ${validation.valid
                                ? "bg-emerald-500/10 border-emerald-600"
                                : "bg-red-500/10 border-red-600"
                                }`}
                        >
                            <p
                                className={`text-sm font-semibold ${validation.valid
                                    ? "text-emerald-400"
                                    : "text-red-400"
                                    }`}
                            >
                                {validation.valid
                                    ? "✓ Valid"
                                    : `✗ ${validation.errors.length} Error(s)`}
                            </p>

                            {!validation.valid && validation.errors.length > 0 && (
                                <ul className="mt-2 space-y-1">
                                    {validation.errors.map((e, i) => (
                                        <li
                                            key={i}
                                            className="text-xs text-red-300"
                                        >
                                            • {e}
                                        </li>
                                    ))}
                                </ul>
                            )}

                            {validation.valid && (
                                <div className="mt-2 flex flex-wrap gap-2">
                                    {validation.indicators_used?.map((ind) => (
                                        <span
                                            key={ind}
                                            className="px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-300 text-xs font-medium"
                                        >
                                            {ind}
                                        </span>
                                    ))}
                                    {validation.symbols?.map((sym) => (
                                        <span
                                            key={sym}
                                            className="px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 text-xs font-medium"
                                        >
                                            {sym}
                                        </span>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}

                    {/* Actions */}
                    <div className="flex items-center gap-3 pt-2">
                        <button
                            onClick={handleValidate}
                            className="text-sm px-4 py-2 rounded-lg bg-slate-700 hover:bg-slate-600 text-white font-medium transition"
                        >
                            🔍 Validate
                        </button>
                        <button
                            onClick={handleSave}
                            disabled={saving}
                            className="text-sm px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white font-medium transition disabled:opacity-50"
                        >
                            {saving
                                ? "Saving..."
                                : existing
                                    ? "Update Strategy"
                                    : "Create Strategy"}
                        </button>
                        <button
                            onClick={onClose}
                            className="text-sm px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 font-medium transition"
                        >
                            Cancel
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}

// ─── Main Page ─────────────────────────────────────────

export default function StrategiesPage() {
    const [strategies, setStrategies] = useState<Strategy[]>([]);
    const [loading, setLoading] = useState(true);
    const [modalOpen, setModalOpen] = useState(false);
    const [editing, setEditing] = useState<Strategy | null>(null);

    const fetchStrategies = useCallback(async () => {
        try {
            const res = await api.get<Strategy[]>("/strategies/");
            setStrategies(res.data);
        } catch {
            // Interceptor handles toast
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchStrategies();
    }, [fetchStrategies]);

    const handleCreate = () => {
        setEditing(null);
        setModalOpen(true);
    };

    const handleEdit = (s: Strategy) => {
        setEditing(s);
        setModalOpen(true);
    };

    const handleDelete = async (id: number) => {
        if (!confirm("Delete this strategy?")) return;
        try {
            await api.delete(`/strategies/${id}`);
            toast.success("Strategy deleted");
            fetchStrategies();
        } catch {
            // Interceptor handles toast
        }
    };

    const handleToggle = async (s: Strategy) => {
        try {
            await api.put(`/strategies/${s.id}`, {
                name: s.name,
                description: s.description,
                json_definition: s.json_definition,
                is_active: !s.is_active,
                tags: s.tags,
            });
            toast.success(s.is_active ? "Strategy paused" : "Strategy activated");
            fetchStrategies();
        } catch {
            // Interceptor handles toast
        }
    };

    return (
        <div className="min-h-screen bg-slate-950 text-white">
            <Toaster
                position="top-right"
                toastOptions={{
                    style: {
                        background: "#1e293b",
                        color: "#f1f5f9",
                        border: "1px solid #334155",
                    },
                }}
            />
            <Navbar />

            <main className="max-w-6xl mx-auto px-4 py-8">
                {/* Header */}
                <div className="flex items-center justify-between mb-8">
                    <div>
                        <h1 className="text-2xl font-bold tracking-tight">
                            📈 Strategy Management
                        </h1>
                        <p className="text-sm text-slate-400 mt-1">
                            Create, validate, and manage your algorithmic
                            trading strategies.
                        </p>
                    </div>
                    <button
                        onClick={handleCreate}
                        className="px-4 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white font-semibold text-sm transition shadow-lg shadow-indigo-500/20"
                    >
                        + New Strategy
                    </button>
                </div>

                {/* Strategy List */}
                {loading ? (
                    <div className="flex items-center justify-center py-20">
                        <div className="animate-spin w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full" />
                    </div>
                ) : strategies.length === 0 ? (
                    <div className="flex flex-col items-center justify-center py-20 text-slate-500">
                        <span className="text-5xl mb-4">📭</span>
                        <p className="text-lg font-medium">
                            No strategies yet
                        </p>
                        <p className="text-sm mt-1">
                            Create your first strategy to get started.
                        </p>
                        <button
                            onClick={handleCreate}
                            className="mt-4 px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-sm font-medium transition border border-slate-700"
                        >
                            + New Strategy
                        </button>
                    </div>
                ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                        {strategies.map((s) => (
                            <StrategyCard
                                key={s.id}
                                strategy={s}
                                onEdit={() => handleEdit(s)}
                                onDelete={() => handleDelete(s.id)}
                                onToggle={() => handleToggle(s)}
                            />
                        ))}
                    </div>
                )}
            </main>

            {/* Modal */}
            <StrategyModal
                open={modalOpen}
                onClose={() => setModalOpen(false)}
                existing={editing}
                onSaved={fetchStrategies}
            />
        </div>
    );
}