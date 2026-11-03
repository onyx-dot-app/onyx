export const OpenSearchSizingCalculator = () => {
  // Bytes per chunk come from backend/onyx/document_index/opensearch/schema.py and a measured
  // 1.56M-chunk corpus. Model dimensions come from backend/onyx/configs/embedding_configs.py.
  const TEXT_PER_CHUNK = 1900;
  // Measured on indices that store a copy of the content, as released Onyx versions do.
  // Releases with #17093 drop that copy, about 500 bytes per chunk.
  const FIXED_BYTES = 2610;
  const MAX_TOTAL_GB = 10_000_000;
  const GRAPH_BYTES = 40;
  const DELETED_OVERHEAD = 1.05;
  const DISK_FILL = 0.75;
  const SHARD_BYTES = 15e9;
  const CACHE_SHARE_FOR_VECTORS = 0.8;

  const PARTS = [
    // One blue scale from the docs primary: darker means more text per GB.
    { label: "Text", sub: "wiki, tickets, chat", textShare: 40, color: "#0050B4", ink: "#FFFFFF" },
    { label: "Office files", sub: "Word, Excel, Google Docs", textShare: 12, color: "#0069ED", ink: "#FFFFFF" },
    { label: "Code", sub: "READMEs and docs only", textShare: 5, color: "#4D9CFF", ink: "#0B2A55" },
    { label: "PDFs and slides", sub: "PDF, PowerPoint", textShare: 4, color: "#A9CCFF", ink: "#0B2A55" },
    { label: "Media and other", sub: "video, images, archives", textShare: 0, color: "#D1D5DB", ink: "#374151", media: true },
  ];
  const MODELS = [
    { name: "Granite Embedding 97M (Onyx default)", dims: 384 },
    { name: "nomic-embed-text-v1", dims: 768 },
    { name: "Google text-embedding-005", dims: 768 },
    { name: "Cohere embed-english-v3.0", dims: 1024 },
    { name: "Voyage large-2-instruct", dims: 1024 },
    { name: "Cohere embed-v4.0", dims: 1536 },
    { name: "OpenAI text-embedding-3-small", dims: 1536 },
    { name: "OpenAI text-embedding-3-large", dims: 3072 },
    { name: "Gemini embedding-001", dims: 3072 },
  ];
  const NODE_RAM = [16, 32, 64];
  const NODE_DISK = [64, 128, 256, 512, 1000, 1500, 3000, 6000];
  // Largest gp3 volume Amazon OpenSearch Service allows for r8g.large, r8g.xlarge and r8g.2xlarge.
  const MAX_DISK_FOR_RAM = { 16: 1500, 32: 3000, 64: 6000 };
  const COPY_HINT = {
    1: "No replica. A node failure stops search until the data is restored.",
    2: "A primary and one replica. Survives one node failure.",
    3: "One copy in each of 3 availability zones. Survives a zone outage.",
  };

  const [totalGB, setTotalGB] = useState(500);
  const [parts, setParts] = useState([0.06, 0.3, 0.06, 0.18, 0.4]);
  const [growth, setGrowth] = useState(30);
  const [modelIndex, setModelIndex] = useState(0);
  const [quant, setQuant] = useState("none");
  const [copies, setCopies] = useState(2);
  const [nodeRamChoice, setNodeRamChoice] = useState("auto");
  const [nodeDiskChoice, setNodeDiskChoice] = useState("auto");
  const [rebuildRoom, setRebuildRoom] = useState(true);
  const barRef = useRef(null);
  const dragRef = useRef(null);

  const fmtBytes = (b) => {
    const g = b / 1e9;
    if (g >= 1000) return (g / 1000).toFixed(g >= 10000 ? 0 : 1) + " TB";
    if (g >= 100) return g.toFixed(0) + " GB";
    if (g >= 10) return g.toFixed(1) + " GB";
    if (g >= 1) return g.toFixed(2) + " GB";
    return Math.max(1, Math.round(g * 1000)) + " MB";
  };
  const fmtCount = (n) =>
    n >= 1e9
      ? (n / 1e9).toFixed(1) + "B"
      : n >= 1e6
        ? (n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + "M"
        : n >= 1e3
          ? Math.round(n / 1e3) + "k"
          : String(Math.round(n));
  const pct = (v) => Math.round(v * 100) + "%";
  const fmtDisk = (gb) => (gb < 1000 ? gb + " GB" : gb / 1000 + " TB");

  // Boundary i sits between part i and part i+1. The last boundary sets the
  // indexable share and scales the document parts together.
  const last = PARTS.length - 2;
  const cumulative = (arr, i) => arr.slice(0, i + 1).reduce((a, b) => a + b, 0);
  const moveBoundary = (i, x) => {
    setParts((prev) => {
      const next = [...prev];
      if (i === last) {
        const target = Math.round(Math.min(1, Math.max(0.01, x)) * 100) / 100;
        const old = cumulative(prev, last);
        for (let k = 0; k <= last; k++) next[k] = old > 0 ? (prev[k] * target) / old : target / (last + 1);
        next[last + 1] = 1 - target;
        return next;
      }
      const lo = i ? cumulative(prev, i - 1) : 0;
      const hi = cumulative(prev, i + 1);
      const at = Math.min(hi, Math.max(lo, Math.round(x * 100) / 100));
      next[i] = at - lo;
      next[i + 1] = hi - at;
      return next;
    });
  };
  const onPointerMove = (e) => {
    if (dragRef.current === null || !barRef.current) return;
    const rect = barRef.current.getBoundingClientRect();
    moveBoundary(dragRef.current, (e.clientX - rect.left) / rect.width);
  };
  const onKey = (i, e) => {
    const step = e.shiftKey ? 0.05 : 0.01;
    const at = cumulative(parts, i);
    if (e.key === "ArrowLeft" || e.key === "ArrowDown") {
      e.preventDefault();
      moveBoundary(i, at - step);
    }
    if (e.key === "ArrowRight" || e.key === "ArrowUp") {
      e.preventDefault();
      moveBoundary(i, at + step);
    }
  };

  // Step 1: what the data needs, one copy.
  const dims = MODELS[modelIndex].dims;
  const totalInput = Number(totalGB);
  const total = Number.isFinite(totalInput) ? Math.min(MAX_TOTAL_GB, Math.max(0, totalInput)) : 0;
  const indexableShare = PARTS.reduce((a, p, k) => a + (p.media ? 0 : parts[k]), 0);
  const textShare = PARTS.reduce((a, p, k) => a + (parts[k] * p.textShare) / 100, 0);
  const indexableGB = total * indexableShare;
  const textGB = total * textShare;
  const chunksToday = (textGB * 1e9) / TEXT_PER_CHUNK;
  const chunks = chunksToday * (1 + growth / 100);
  const quantBytes = quant === "sq7" ? dims : quant === "sq1" ? dims / 8 : 0;
  const bytesPerChunk = (FIXED_BYTES + GRAPH_BYTES + 4 * dims + quantBytes) * DELETED_OVERHEAD;
  const indexOneCopy = chunks * bytesPerChunk;
  const hotPerChunk = (quant === "none" ? 4 * dims : quantBytes) + GRAPH_BYTES;
  const hotOneCopy = chunks * hotPerChunk;

  // Step 2: lay the copies out on nodes.
  const zones = copies === 3 ? 3 : 1;
  const allCopies = indexOneCopy * copies;
  const provision = (allCopies * (rebuildRoom ? 2 : 1)) / DISK_FILL;
  const hotAll = hotOneCopy * copies;
  // Recommended memory is the smallest node size that fits on one node per copy;
  // otherwise the largest, so the cluster adds nodes instead of growing nodes.
  const cacheFor = (ram) => (ram - Math.min(ram / 2, 31)) * CACHE_SHARE_FOR_VECTORS * 1e9;
  const baseNodes = Math.ceil(copies / zones) * zones;
  const nodesFor = (ram) =>
    Math.ceil(Math.max(copies, Math.ceil(hotAll / cacheFor(ram)), Math.ceil(provision / (MAX_DISK_FOR_RAM[ram] * 1e9))) / zones) * zones;
  const recommendedRam = NODE_RAM.find((r) => nodesFor(r) <= baseNodes) || NODE_RAM[NODE_RAM.length - 1];
  const nodeRam = nodeRamChoice === "auto" ? recommendedRam : nodeRamChoice;
  const heapGB = Math.min(nodeRam / 2, 31);
  const cachePerNode = (nodeRam - heapGB) * CACHE_SHARE_FOR_VECTORS * 1e9;
  const nodesForMemory = Math.ceil(hotAll / cachePerNode);
  // Recommended storage fills up at the same node count that memory and copies need.
  const maxDisk = MAX_DISK_FOR_RAM[nodeRam];
  const diskOptions = NODE_DISK.filter((d) => d <= maxDisk);
  const nodesWithoutStorage = Math.ceil(Math.max(copies, nodesForMemory) / zones) * zones;
  const neededPerNode = provision / 1e9 / nodesWithoutStorage;
  const recommendedDisk = diskOptions.find((d) => d >= neededPerNode) || maxDisk;
  const nodeDisk = nodeDiskChoice === "auto" ? recommendedDisk : Math.min(nodeDiskChoice, maxDisk);
  const nodesForStorage = Math.ceil(provision / (nodeDisk * 1e9));
  const nodes = Math.ceil(Math.max(copies, nodesForMemory, nodesForStorage) / zones) * zones;
  const limit = nodes > nodesWithoutStorage ? "storage" : nodesForMemory > copies ? "memory" : "copies";
  // Shards are whole units, so pick a primary count whose copies divide evenly over the
  // nodes. Then no node holds more than its share of the vectors and the data.
  const gcd = (a, b) => (b === 0 ? a : gcd(b, a % b));
  const primaryStep = nodes / gcd(copies, nodes);
  const primaries =
    Math.ceil(Math.max(1, Math.ceil(indexOneCopy / SHARD_BYTES), Math.ceil(nodes / copies)) / primaryStep) * primaryStep;

  const card = "rounded-2xl border border-gray-200 dark:border-white/10 bg-white dark:bg-transparent p-5";
  const label = "text-base font-medium text-gray-900 dark:text-gray-200";
  const hint = "text-sm text-gray-500 dark:text-gray-400";
  const input =
    "rounded-lg border border-gray-200 dark:border-white/10 bg-white dark:bg-white/5 px-3 py-1.5 text-base tabular-nums text-gray-900 dark:text-gray-100";
  const big = "text-2xl font-semibold tabular-nums text-gray-900 dark:text-white";
  const seg = (active) =>
    "px-3 py-1.5 text-base border-r last:border-r-0 border-gray-200 dark:border-white/10 " +
    (active
      ? "bg-primary text-white dark:bg-primary-light dark:text-gray-950"
      : "bg-white dark:bg-white/5 text-gray-700 dark:text-gray-300");
  const segmented = ({ options, value, onChange, ariaLabel }) => (
    <div role="group" aria-label={ariaLabel} className="inline-flex flex-wrap overflow-hidden rounded-lg border border-gray-200 dark:border-white/10">
      {options.map(([v, text]) => (
        <button key={String(v)} type="button" aria-pressed={value === v} className={seg(value === v)} onClick={() => onChange(v)}>
          {text}
        </button>
      ))}
    </div>
  );
  const stat = ({ value, text }) => (
    <div className="border-t-2 border-gray-200 dark:border-white/10 pt-2">
      <div className="text-2xl font-semibold tabular-nums text-gray-900 dark:text-white">{value}</div>
      <div className={hint}>{text}</div>
    </div>
  );

  return (
    <div className="os-sizing not-prose my-6 space-y-6">
      <style>{`
        .os-sizing input[type="number"], .os-sizing select { transition: border-color 120ms, box-shadow 120ms; }
        .os-sizing input[type="number"]:hover, .os-sizing select:hover { border-color: #D1D5DB; }
        .os-sizing input[type="number"]:focus, .os-sizing select:focus { outline: none; border-color: #0069ED; box-shadow: 0 0 0 3px rgba(0, 105, 237, 0.2); }
        .dark .os-sizing input[type="number"]:hover, .dark .os-sizing select:hover { border-color: rgba(255, 255, 255, 0.2); }
        .dark .os-sizing input[type="number"]:focus, .dark .os-sizing select:focus { border-color: #4D9CFF; box-shadow: 0 0 0 3px rgba(77, 156, 255, 0.25); }
      `}</style>
      <div className="grid gap-4">
        <div className={card + " space-y-5"}>
          <div className="text-lg font-semibold text-gray-900 dark:text-white">1. What your data needs</div>
          <div className="space-y-1.5">
            <label htmlFor="os-total" className={label}>Total storage</label>
            <div className="flex items-center gap-2">
              <input id="os-total" type="number" min="1" max="10000000" step="10" value={totalGB} onChange={(e) => setTotalGB(Number(e.target.value) > MAX_TOTAL_GB ? String(MAX_TOTAL_GB) : e.target.value)} className={input + " w-32"} />
              <span className={hint}>GB</span>
            </div>
          </div>
          <div className="space-y-2">
            <div className={label} id="os-mix-label">Storage mix</div>
            <div
              ref={barRef}
              role="group"
              aria-labelledby="os-mix-label"
              className="relative flex h-9 select-none rounded-lg"
              style={{ touchAction: "none" }}
              onPointerMove={onPointerMove}
              onPointerUp={() => (dragRef.current = null)}
            >
              {PARTS.map((p, k) => (
                <div
                  key={p.label}
                  className={"flex items-center justify-center overflow-hidden whitespace-nowrap text-sm font-medium tabular-nums" + (k === 0 ? " rounded-l-lg" : "") + (k === PARTS.length - 1 ? " rounded-r-lg" : "")}
                  style={{ width: parts[k] * 100 + "%", background: p.color, color: p.ink }}
                >
                  {parts[k] >= 0.12 ? pct(parts[k]) : ""}
                </div>
              ))}
              {PARTS.slice(1).map((p, i) => (
                <div
                  key={"h" + i}
                  role="slider"
                  tabIndex={0}
                  aria-label={"Boundary between " + PARTS[i].label + " and " + p.label}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={Math.round(cumulative(parts, i) * 100)}
                  className="absolute -top-1 h-11 w-2.5 -ml-[5px] cursor-ew-resize rounded-full border border-gray-300 bg-white shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-primary dark:border-gray-500"
                  style={{ left: cumulative(parts, i) * 100 + "%", touchAction: "none" }}
                  onPointerDown={(e) => {
                    e.preventDefault();
                    e.currentTarget.focus();
                    dragRef.current = i;
                    barRef.current && barRef.current.setPointerCapture(e.pointerId);
                  }}
                  onKeyDown={(e) => onKey(i, e)}
                />
              ))}
            </div>
            <div className="space-y-3 pt-2">
              {PARTS.map((p, k) => (
                <div key={p.label} className="flex items-start gap-3">
                  <span className="mt-1.5 h-3 w-3 shrink-0 rounded-sm" style={{ background: p.color }} />
                  <div className="min-w-0 flex-1">
                    <div className="text-base text-gray-900 dark:text-gray-100">{p.label}</div>
                    <div className={hint + " truncate"}>{p.sub}</div>
                  </div>
                  <div className="shrink-0 text-right">
                    <div className="text-base tabular-nums text-gray-900 dark:text-gray-100">{fmtBytes(total * parts[k] * 1e9)}</div>
                    <div className={hint + " tabular-nums"}>{pct(parts[k])}</div>
                  </div>
                </div>
              ))}
            </div>
            <div className="grid grid-cols-2 gap-3 border-t border-gray-200 pt-3 dark:border-white/10">
              <div><div className={hint}>Indexable</div><div className="text-xl font-semibold tabular-nums text-gray-900 dark:text-white">{fmtBytes(indexableGB * 1e9)}</div></div>
              <div><div className={hint}>Text</div><div className="text-xl font-semibold tabular-nums text-gray-900 dark:text-white">{fmtBytes(textGB * 1e9)}</div></div>
            </div>
          </div>
          <div className="space-y-1.5">
            <label htmlFor="os-growth" className={label}>Growth to plan for</label>
            <div className="flex items-center gap-3">
              <input id="os-growth" type="range" min="0" max="300" step="10" value={growth} onChange={(e) => setGrowth(Number(e.target.value))} className="flex-1 accent-primary" />
              <span className="w-12 text-right tabular-nums text-base text-gray-900 dark:text-gray-100">{growth}%</span>
            </div>
          </div>
          <details className="group border-t border-gray-200 pt-4 dark:border-white/10">
            <summary className="cursor-pointer list-none [&::-webkit-details-marker]:hidden">
              <div className={label + " flex items-center gap-2 whitespace-nowrap"}>
                <span className="inline-block w-3 transition-transform group-open:rotate-90">›</span>
                Advanced settings
              </div>
              <div className={hint + " ml-5 mt-0.5"}>
                {MODELS[modelIndex].name + " · " + (quant === "none" ? "no quantization" : quant === "sq7" ? "7-bit quantization" : "1-bit quantization")}
              </div>
            </summary>
            <div className="mt-4 space-y-5">
              <div className="space-y-1.5">
                <label htmlFor="os-model" className={label}>Embedding model</label>
                <select id="os-model" value={modelIndex} onChange={(e) => setModelIndex(Number(e.target.value))} className={input + " w-full"}>
                  {MODELS.map((m, k) => (
                    <option key={m.name} value={k}>{m.name + " · " + m.dims + " dims"}</option>
                  ))}
                </select>
              </div>
              <div className="space-y-1.5">
                <div className={label}>Vector quantization</div>
                {segmented({ ariaLabel: "Vector quantization", value: quant, onChange: setQuant, options: [["none", "None"], ["sq7", "7-bit"], ["sq1", "1-bit"]] })}
                <div className={hint}>Quantization cuts the memory that search needs. It adds a little storage, because the full vectors stay on disk. 1-bit needs OpenSearch 3.6 or later.</div>
              </div>
            </div>
          </details>
        </div>

        <div className={card + " h-fit space-y-4"}>
          <div className="text-lg font-semibold text-gray-900 dark:text-white">Result</div>
          <div className="grid gap-4 sm:grid-cols-3">
            {stat({ value: fmtCount(chunks), text: "chunks, with " + growth + "% growth (" + fmtCount(chunksToday) + " today)" })}
            {stat({ value: fmtBytes(indexOneCopy), text: "index size, one copy" })}
            {stat({ value: fmtBytes(hotOneCopy), text: "RAM for vector search, one copy" })}
          </div>
          <details className="text-sm">
            <summary className="cursor-pointer font-medium text-gray-900 dark:text-gray-200">How this is calculated</summary>
            <table className="mt-2 w-full text-sm">
              <tbody>
                {[
                  ["Total storage", fmtBytes(total * 1e9)],
                  ["× text share of the storage mix (" + (textShare * 100).toFixed(1) + "%)", fmtBytes(textGB * 1e9)],
                  ["÷ ~1,900 characters per chunk", fmtCount(chunksToday) + " chunks"],
                  ["× growth (" + growth + "%)", fmtCount(chunks) + " chunks"],
                  ["× " + Math.round(bytesPerChunk).toLocaleString() + " B per chunk (" + dims + " dims)", fmtBytes(indexOneCopy)],
                  ["RAM: chunks × " + Math.round(hotPerChunk).toLocaleString() + " B", fmtBytes(hotOneCopy)],
                ].map(([a, b]) => (
                  <tr key={a} className="border-t border-gray-200 dark:border-white/10">
                    <td className="py-1.5 pr-2 text-gray-700 dark:text-gray-300">{a}</td>
                    <td className="py-1.5 text-right tabular-nums text-gray-900 dark:text-gray-100">{b}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </div>
      </div>

      <div className="grid gap-4">
        <div className={card + " space-y-5"}>
          <div className="text-lg font-semibold text-gray-900 dark:text-white">2. How to run it</div>
          <div className="space-y-1.5">
            <div className={label}>Copies of the data</div>
            {segmented({ ariaLabel: "Copies of the data", value: copies, onChange: setCopies, options: [[1, "1"], [2, "2"], [3, "3"]] })}
            <div className={hint}>{COPY_HINT[copies]}</div>
          </div>
          <div className="grid gap-5 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label htmlFor="os-node" className={label}>Memory per data node</label>
              <select
                id="os-node"
                value={nodeRamChoice === "auto" ? "auto" : String(nodeRam)}
                onChange={(e) => setNodeRamChoice(e.target.value === "auto" ? "auto" : Number(e.target.value))}
                className={input + " w-full"}
              >
                <option value="auto">{"Recommended (" + recommendedRam + " GB)"}</option>
                {NODE_RAM.map((r) => (
                  <option key={r} value={String(r)}>{r + " GB"}</option>
                ))}
              </select>
              <div className={hint}>Recommended memory is the smallest node that holds the data on the fewest nodes. 64 GB at most.</div>
            </div>
            <div className="space-y-1.5">
              <label htmlFor="os-disk" className={label}>Storage per data node</label>
              <select
                id="os-disk"
                value={nodeDiskChoice === "auto" ? "auto" : String(nodeDisk)}
                onChange={(e) => setNodeDiskChoice(e.target.value === "auto" ? "auto" : Number(e.target.value))}
                className={input + " w-full"}
              >
                <option value="auto">{"Recommended (" + fmtDisk(recommendedDisk) + ")"}</option>
                {diskOptions.map((d) => (
                  <option key={d} value={String(d)}>{fmtDisk(d)}</option>
                ))}
              </select>
              <div className={hint}>Recommended storage fills up at the same node count that memory needs.</div>
            </div>
          </div>
          <div className="space-y-1.5">
            <div className={label}>Room to rebuild the index</div>
            {segmented({ ariaLabel: "Room to rebuild the index", value: rebuildRoom, onChange: setRebuildRoom, options: [[true, "Yes"], [false, "No"]] })}
            <div className={hint}>A change of embedding model or quantization builds a second index while the first one serves search.</div>
          </div>
        </div>

        <div className={card + " h-fit space-y-4"}>
          <div className="text-lg font-semibold text-gray-900 dark:text-white">Cluster</div>
          <div className="rounded-xl bg-primary/10 p-4 dark:bg-primary-light/10">
            <div className="text-xl font-semibold tabular-nums text-gray-900 dark:text-white">{nodes + (nodes === 1 ? " data node · " : " data nodes · ") + nodeRam + " GB RAM · " + fmtDisk(nodeDisk) + " storage each"}</div>
            <div className={hint + " mt-1"}>
              {limit === "storage"
                ? "Set by storage: the cluster needs " + fmtBytes(provision) + " of disk, and each node has " + fmtDisk(nodeDisk) + "."
                : limit === "memory"
                ? "Set by memory: the vectors need " + fmtBytes(hotAll) + " of file cache, and each node has about " + fmtBytes(cachePerNode) + "."
                : "Set by the copy count: " + copies + (copies === 1 ? " copy needs" : " copies need") + " at least " + copies + (copies === 1 ? " node" : " nodes") + (zones === 3 ? ", one in each zone" : "") + "."}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            {stat({ value: fmtBytes(provision), text: "storage to provision, all nodes" })}
            {stat({ value: fmtBytes(provision / nodes), text: "storage needed per node" })}
            {stat({ value: fmtBytes(hotAll), text: "RAM for vector search, all copies" })}
            {stat({ value: String(primaries), text: "primary shards" })}
          </div>
          <div className="space-y-1.5">
            <div className={label}>Onyx settings</div>
            <pre className="overflow-x-auto rounded-lg bg-gray-50 p-3 font-mono text-sm text-gray-900 dark:bg-white/5 dark:text-gray-100">{"OPENSEARCH_INDEX_NUM_SHARDS=" + primaries + "\nOPENSEARCH_INDEX_NUM_REPLICAS=" + (copies - 1)}</pre>
            <div className={hint}>Set these before the first indexing run. Onyx fixes the shard count when it creates the index.</div>
          </div>
          {limit === "memory" && quant === "none" ? (
            <div className="rounded-lg bg-amber-500/10 p-3 text-sm text-amber-800 dark:text-amber-300">Memory sets the node count. 1-bit quantization (OpenSearch 3.6 or later) stores vectors 32× smaller.</div>
          ) : null}
          {limit === "storage" ? (
            <div className="rounded-lg bg-amber-500/10 p-3 text-sm text-amber-800 dark:text-amber-300">Storage sets the node count. Larger disks per node need fewer nodes. Without room to rebuild, the cluster needs half the storage.</div>
          ) : null}
        </div>
      </div>
    </div>
  );
};
