"""Build region-adjacency graphs from official boundary data.

Run once; the resulting JSON files in data/ are committed so the solver and the
visualisation work offline without geopandas.

Sources
-------
- Curitiba Regionais: IPPUC geodownloads (Decreto Municipal 844/2018).
- RMC municipalities: IBGE malhas API v3 + IBGE localidades API v1.

Adjacency rule
--------------
Two regions are adjacent only if their boundaries share a segment of at least
MIN_SHARED_M metres. Touching at a single point does not count (this is the
adjacency notion used by the Four Colour Theorem). A small buffer TOLERANCE_M
absorbs digitisation gaps between neighbouring polygons.
"""

from __future__ import annotations

import json
import unicodedata
import zipfile
from pathlib import Path

import geopandas as gpd
import networkx as nx
import requests
from shapely.geometry import mapping

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data"

METRIC_CRS = "EPSG:31982"  # SIRGAS 2000 / UTM zone 22S
TOLERANCE_M = 5.0
MIN_SHARED_M = 100.0

IPPUC_REGIONAIS = "https://ippuc.org.br/geodownloads/SHAPES_SIRGAS/DIVISA_DE_REGIONAIS_SIRGAS.zip"
IBGE_PR_MESH = (
    "https://servicodados.ibge.gov.br/api/v3/malhas/estados/41"
    "?formato=application/vnd.geo+json&intrarregiao=municipio&qualidade=maxima"
)
IBGE_PR_NAMES = "https://servicodados.ibge.gov.br/api/v1/localidades/estados/41/municipios"

# Região Metropolitana de Curitiba (29 municipalities).
RMC = [
    "Adrianópolis", "Agudos do Sul", "Almirante Tamandaré", "Araucária", "Balsa Nova",
    "Bocaiúva do Sul", "Campina Grande do Sul", "Campo do Tenente", "Campo Largo",
    "Campo Magro", "Cerro Azul", "Colombo", "Contenda", "Curitiba", "Doutor Ulysses",
    "Fazenda Rio Grande", "Itaperuçu", "Lapa", "Mandirituba", "Piên", "Pinhais",
    "Piraquara", "Quatro Barras", "Quitandinha", "Rio Branco do Sul", "Rio Negro",
    "São José dos Pinhais", "Tijucas do Sul", "Tunas do Paraná",
]


def slug(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return "_".join(ascii_name.lower().replace("-", " ").split())


def fetch(url: str, target: Path) -> Path:
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        response = requests.get(url, timeout=180)
        response.raise_for_status()
        target.write_bytes(response.content)
    return target


def load_regionais() -> gpd.GeoDataFrame:
    path = fetch(IPPUC_REGIONAIS, RAW / "regionais.zip")
    zipfile.ZipFile(path).testzip()
    gdf = gpd.read_file(f"zip://{path}")
    gdf["name"] = gdf["NOME"].str.title().replace({"Cic": "CIC"})
    return gdf[["name", "geometry"]]


def load_rmc() -> gpd.GeoDataFrame:
    mesh = fetch(IBGE_PR_MESH, RAW / "pr_municipios.geojson")
    names = json.loads(fetch(IBGE_PR_NAMES, RAW / "pr_municipios_nomes.json").read_text("utf-8"))
    by_slug = {slug(m["nome"]): str(m["id"]) for m in names}

    missing = [n for n in RMC if slug(n) not in by_slug]
    if missing:
        raise SystemExit(f"RMC names not found in IBGE list: {missing}")
    code_to_name = {by_slug[slug(n)]: n for n in RMC}

    gdf = gpd.read_file(mesh)
    gdf = gdf[gdf["codarea"].isin(code_to_name)].copy()
    gdf["name"] = gdf["codarea"].map(code_to_name)
    return gdf[["name", "geometry"]]


def adjacency(gdf: gpd.GeoDataFrame) -> list[dict]:
    """Return edges whose shared boundary is at least MIN_SHARED_M long."""
    metric = gdf.to_crs(METRIC_CRS).reset_index(drop=True)
    edges = []
    for i in range(len(metric)):
        a = metric.geometry[i]
        a_buffered = a.buffer(TOLERANCE_M)
        for j in range(i + 1, len(metric)):
            b = metric.geometry[j]
            if not a_buffered.intersects(b):
                continue
            shared = b.boundary.intersection(a_buffered).length
            if shared >= MIN_SHARED_M:
                edges.append({
                    "a": slug(metric["name"][i]),
                    "b": slug(metric["name"][j]),
                    "shared_border_m": round(shared, 1),
                })
    return edges


def validate(regions: list[dict], edges: list[dict]) -> nx.Graph:
    graph = nx.Graph()
    graph.add_nodes_from(r["id"] for r in regions)
    graph.add_edges_from((e["a"], e["b"]) for e in edges)
    planar, _ = nx.check_planarity(graph)
    if not nx.is_connected(graph):
        raise SystemExit(f"graph is not connected: {list(nx.connected_components(graph))}")
    if not planar:
        raise SystemExit("graph is not planar; check tolerance/threshold")
    return graph


def export(gdf: gpd.GeoDataFrame, map_id: str, title: str, source: str, simplify_m: float) -> None:
    edges = adjacency(gdf)

    # Simplify in metres, then store lon/lat so plotting needs no projection library.
    metric = gdf.to_crs(METRIC_CRS)
    metric["geometry"] = metric.geometry.simplify(simplify_m, preserve_topology=True)
    wgs84 = metric.to_crs("EPSG:4326")
    centroids = metric.geometry.representative_point().to_crs("EPSG:4326")

    regions = []
    for (_, row), point in zip(wgs84.iterrows(), centroids):
        regions.append({
            "id": slug(row["name"]),
            "name": row["name"],
            "label_point": [round(point.x, 6), round(point.y, 6)],
            "geometry": mapping(row.geometry),
        })
    regions.sort(key=lambda r: r["id"])

    graph = validate(regions, edges)
    payload = {
        "id": map_id,
        "title": title,
        "source": source,
        "adjacency_rule": {
            "shared_boundary_min_m": MIN_SHARED_M,
            "tolerance_m": TOLERANCE_M,
            "crs": METRIC_CRS,
        },
        "regions": regions,
        "edges": edges,
    }
    target = OUT / f"{map_id}.json"
    target.write_text(_dump(payload), encoding="utf-8")

    print(f"{target.name}: {graph.number_of_nodes()} regions, {graph.number_of_edges()} edges, "
          f"max degree {max(d for _, d in graph.degree())}")
    for e in edges:
        print(f"  {e['a']:>24} -- {e['b']:<24} {e['shared_border_m']:>10.1f} m")


def _dump(payload: dict) -> str:
    # Coordinates rounded to ~10 cm keep the files small and diffs readable.
    def rounder(obj):
        if isinstance(obj, float):
            return round(obj, 6)
        if isinstance(obj, (list, tuple)):
            return [rounder(x) for x in obj]
        if isinstance(obj, dict):
            return {k: rounder(v) for k, v in obj.items()}
        return obj
    return json.dumps(rounder(payload), ensure_ascii=False, indent=1)


def main() -> None:
    export(load_regionais(), "curitiba_regionais", "Curitiba — Administrative Regions (Regionais)",
           "IPPUC, Decreto Municipal 844/2018", simplify_m=20.0)
    export(load_rmc(), "rmc_municipalities", "Curitiba Metropolitan Region (RMC) — Municipalities",
           "IBGE malhas API v3 / localidades API v1", simplify_m=100.0)


if __name__ == "__main__":
    main()
