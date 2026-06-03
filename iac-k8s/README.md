# iac-k8s

How we build and run hardened **Google Kubernetes Engine (GKE)** clusters on Google Cloud through a simple operator console — across environments (dev/stage/prod) and purposes (Fleet Operations Plane, Management Plane).

## Read in this order
1. **[requirements.md](requirements.md)** — what we need and why, under four guiding principles (Simplicity, Audit-ready, Secure-by-design, Cost-transparency).
2. **[explore.md](explore.md)** — the journey: what we debated, the build-vs-buy decision, and the proof-of-concept (what worked, what broke).
3. **[design.md](design.md)** — the end-to-end design and build contract (with architecture diagram). A fresh session can build the console from this.
4. **[operator-console.md](operator-console.md)** — the console screens and features. Live mockup: **[console-mockup.html](console-mockup.html)** (Bootstrap, static).

## Decision in one line
Build on **Terraform + GitHub Actions + a custom console**, with **ArgoCD** enforcing security as a closed loop and **GKE Connect Gateway** for access — simplest path that meets the goals at ≤6 clusters. Full rationale and the alternatives considered are in [explore.md](explore.md) and [`archive/build-vs-buy-platform.md`](archive/build-vs-buy-platform.md).

## Folder
- `diagrams/` — architecture pictures (Excalidraw sources + SVG exports).
- `archive/` — earlier working documents and the proof-of-concept records (frozen for history).
