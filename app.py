# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "streamlit",
#   "pandas",
#   "matplotlib",
#   "psycopg2-binary",
#   "sqlalchemy",
# ]
# ///

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import io
import math
import random
import re
import matplotlib.patches as patches
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st
from sqlalchemy import text

# ==============================================================================
# 1. DATABASE SETUP & PERSISTENCE (NEON POSTGRESQL)
# ==============================================================================


def get_db():
  return st.connection("neon", type="sql")


def init_db():
  conn = get_db()
  with conn.session as s:
    s.execute(
        text("""
            CREATE TABLE IF NOT EXISTS students (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    )
    s.execute(
        text("""
            CREATE TABLE IF NOT EXISTS topic_mastery (
                student_id INTEGER,
                topic TEXT,
                mastery REAL DEFAULT 0.0,
                PRIMARY KEY (student_id, topic)
            )
        """)
    )
    s.execute(
        text("""
            CREATE TABLE IF NOT EXISTS attempt_logs (
                id SERIAL PRIMARY KEY,
                student_id INTEGER,
                topic TEXT,
                template_id TEXT,
                is_correct INTEGER,
                selected_answer TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    )
    s.commit()


def list_students():
  conn = get_db()
  df = conn.query("SELECT id, name FROM students ORDER BY name ASC")
  return df.to_dict(orient="records")


def get_or_create_student(name: str):
  clean_name = name.strip().capitalize()
  if not clean_name:
    return None
  conn = get_db()
  df = conn.query(
      "SELECT id, name FROM students WHERE name = :name",
      params={"name": clean_name},
  )
  if not df.empty:
    return {"id": int(df.iloc[0]["id"]), "name": df.iloc[0]["name"]}

  with conn.session as s:
    result = s.execute(
        text(
            "INSERT INTO students (name) VALUES (:name) RETURNING id, name"
        ),
        {"name": clean_name},
    )
    row = result.fetchone()
    s.commit()
    return {"id": int(row[0]), "name": row[1]}


def load_mastery(student_id: int, all_topics: list[str]) -> dict[str, float]:
  conn = get_db()
  df = conn.query(
      "SELECT topic, mastery FROM topic_mastery WHERE student_id = :sid",
      params={"sid": student_id},
  )
  mastery = {row["topic"]: row["mastery"] for _, row in df.iterrows()}

  with conn.session as s:
    for topic in all_topics:
      if topic not in mastery:
        mastery[topic] = 0.0
        s.execute(
            text(
                "INSERT INTO topic_mastery (student_id, topic, mastery) VALUES"
                " (:sid, :top, 0.0) ON CONFLICT (student_id, topic) DO NOTHING"
            ),
            {"sid": student_id, "top": topic},
        )
    s.commit()
  return mastery


def reset_student_progress(student_id: int, all_topics: list[str]):
  conn = get_db()
  with conn.session as s:
    s.execute(
        text("DELETE FROM attempt_logs WHERE student_id = :sid"),
        {"sid": student_id},
    )
    for topic in all_topics:
      s.execute(
          text(
              "INSERT INTO topic_mastery (student_id, topic, mastery) VALUES"
              " (:sid, :top, 0.0) ON CONFLICT (student_id, topic) DO UPDATE SET"
              " mastery = 0.0"
          ),
          {"sid": student_id, "top": topic},
      )
    s.commit()


def record_attempt(
    student_id: int,
    topic: str,
    template_id: str,
    is_correct: bool,
    selected_answer: str,
    new_mastery: float,
):
  conn = get_db()
  with conn.session as s:
    s.execute(
        text("""
            INSERT INTO attempt_logs (student_id, topic, template_id, is_correct, selected_answer)
            VALUES (:sid, :top, :tid, :corr, :ans)
        """),
        {
            "sid": student_id,
            "top": topic,
            "tid": template_id,
            "corr": 1 if is_correct else 0,
            "ans": selected_answer,
        },
    )
    s.execute(
        text("""
            INSERT INTO topic_mastery (student_id, topic, mastery) VALUES (:sid, :top, :mast)
            ON CONFLICT (student_id, topic) DO UPDATE SET mastery = :mast
        """),
        {"sid": student_id, "top": topic, "mast": new_mastery},
    )
    s.commit()


# ==============================================================================
# 2. TEACHER REPOSITORY: MCGRAW-HILL REVEAL MATH LESSONS
# ==============================================================================
MINI_LESSONS = {
    "Unit 2: Volume": {
        "title": "Unit 2: Volume of Prisms & Composite Solids",
        "concept": """
### 👩‍🏫 Unit 2: Volume Foundations
* **What is Volume?** The space occupied by a 3-dimensional solid figure, measured in **cubic units**.
* **Key Definitions (Lessons 2-1 to 2-4):**
  * **Unit Cube:** A cube with edge lengths of $1$ unit (Volume $= 1\\text{ cubic unit}$).
  * **Rectangular Prism:** A 3D solid with $6$ rectangular faces.
  * **Composite / Compound Solid:** A solid made of two or more joined solids.
  * **Formula:** An equation describing relationships between quantities ($V = l \\times w \\times h$ or $V = B \\times h$).
* **Associative Property (Lesson 2-3):** 
  $$(l \\times w) \\times h = l \\times (w \\times h)$$
  Grouping factors differently does not change the total volume.
* **Liquid Volume vs. Container Height (Lesson 2-5):**
  When finding water volume in a pool or tank, use the **depth of the liquid**, NOT the height of the container wall!
        """,
        "example": """
* **Decomposing a Warehouse (Lesson 2-4):**
  * Section A: $20\\text{ ft wide} \\times 25\\text{ ft deep} \\times 50\\text{ ft tall} = 25,000\\text{ cu ft}$
  * Section B: $30\\text{ ft wide} \\times 50\\text{ ft deep} \\times 25\\text{ ft tall} = 37,500\\text{ cu ft}$
  * Total Volume $= 25,000 + 37,500 = \\mathbf{62,500\\text{ cu ft}}$.
        """,
        "trap": (
            "Don't multiply the wall height by mistake when finding liquid"
            " volume! Always verify whether the problem asks for the"
            " container's capacity or the liquid's volume."
        ),
    },
    "Unit 3: Place Value and Number Relationships": {
        "title": "Unit 3: Place Value and Number Relationships",
        "concept": """
### 👩‍🏫 Unit 3: Decimal Place Value & Powers of 10
* **The 10-to-1 Relationship:**
  * One step left $\\rightarrow$ **10 times greater** ($0.02$ is 10 times $0.002$).
  * One step right $\\rightarrow$ **1/10 of** ($0.05$ is $1/10$ of $0.5$).
* **Rounding Decimals (Lesson 3-5):**
  1. Circle target place value digit.
  2. Look at right-side neighbor: **5 or more rounds up**, **4 or less stays the same**.
        """,
        "example": """
* Rounding $2.755$ to hundredths: Neighbor digit is $5 \\ge 5 \\rightarrow \\mathbf{2.76}$.
* Word Form: $44.259 \\rightarrow$ *"forty-four and two hundred fifty-nine thousandths"*.
        """,
        "trap": (
            "Place is the name (*thousandths*). Value is the numeric quantity"
            " (*0.009* or *9/1,000*)."
        ),
    },
    "Unit 4: Add and Subtract Decimals": {
        "title": "Unit 4: Addition and Subtraction of Decimals",
        "concept": (
            "Always line up the decimal points vertically so identical place"
            " values align. Fill missing positions with placeholder zeros."
        ),
        "example": "$24.75 + 5.40 = 30.15$.",
        "trap": "Never line up decimal numbers along the right edge!",
    },
    "Unit 5: Multiply Multi-Digit Whole Numbers": {
        "title": "Unit 5: Multi-Digit Whole Number Multiplication",
        "concept": (
            "Multiply by the ones digit, then insert a 0 placeholder before"
            " multiplying by the tens digit."
        ),
        "example": "$142 \\times 23 = 426 + 2,840 = 3,266$.",
        "trap": "Remember the 0 placeholder on the second line!",
    },
    "Unit 6: Multiply Decimals": {
        "title": "Unit 6: Multiplying Decimals",
        "concept": (
            "Multiply like whole numbers. Then count total decimal places in"
            " both factors and move the decimal left in the product."
        ),
        "example": (
            "$3.2$ (1 place) $\\times 0.4$ (1 place) $= 1.28$ (2 places)."
        ),
        "trap": "Do not line up decimal points when multiplying!",
    },
    "Unit 7: Divide Whole Numbers": {
        "title": "Unit 7: Dividing Whole Numbers",
        "concept": (
            "Divide, Multiply, Subtract, Bring down. State leftovers as"
            " remainders (e.g., 31 R1)."
        ),
        "example": "$125 \\div 4 = 31\\text{ R}1$.",
        "trap": "The remainder must always be smaller than the divisor!",
    },
}

# ==============================================================================
# 3. HELPER ARRAYS & FUNCTIONS
# ==============================================================================
ONES_WORDS = [
    "",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
]
TEENS_WORDS = [
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
TENS_WORDS = [
    "",
    "",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
]


def number_to_word_2digit(n):
  if n < 10:
    return ONES_WORDS[n]
  if n < 20:
    return TEENS_WORDS[n - 10]
  t, r = n // 10, n % 10
  return TENS_WORDS[t] + (f"-{ONES_WORDS[r]}" if r > 0 else "")


# ==============================================================================
# 4. 3D VISUAL ENGINE & DIAGRAM GENERATORS (EXACT WAREHOUSE LABEL FIX)
# ==============================================================================
def project_oblique(x, y, z, scale_d=0.55):
  rad = math.radians(32)
  px = x + z * scale_d * math.cos(rad)
  py = y + z * scale_d * math.sin(rad)
  return px, py


def render_box(
    ax,
    x0,
    y0,
    z0,
    lx,
    ly,
    lz,
    col_front="#00a8cc",
    col_top="#bbf2f6",
    col_side="#006a8e",
    label=None,
):
  edge_col = "#042f2e"
  f_pts = [
      project_oblique(x0, y0, z0),
      project_oblique(x0 + lx, y0, z0),
      project_oblique(x0 + lx, y0 + ly, z0),
      project_oblique(x0, y0 + ly, z0),
  ]
  t_pts = [
      project_oblique(x0, y0 + ly, z0),
      project_oblique(x0 + lx, y0 + ly, z0),
      project_oblique(x0 + lx, y0 + ly, z0 + lz),
      project_oblique(x0, y0 + ly, z0 + lz),
  ]
  s_pts = [
      project_oblique(x0 + lx, y0, z0),
      project_oblique(x0 + lx, y0, z0 + lz),
      project_oblique(x0 + lx, y0 + ly, z0 + lz),
      project_oblique(x0 + lx, y0 + ly, z0),
  ]

  ax.add_patch(
      patches.Polygon(
          f_pts, closed=True, facecolor=col_front, edgecolor=edge_col, lw=1.6
      )
  )
  ax.add_patch(
      patches.Polygon(
          t_pts, closed=True, facecolor=col_top, edgecolor=edge_col, lw=1.6
      )
  )
  ax.add_patch(
      patches.Polygon(
          s_pts, closed=True, facecolor=col_side, edgecolor=edge_col, lw=1.6
      )
  )

  if label:
    cx, cy = x0 + lx / 2, y0 + ly / 2
    px, py = project_oblique(cx, cy, z0)
    ax.text(
        px,
        py,
        label,
        fontsize=20,
        fontweight="bold",
        color="white",
        ha="center",
        va="center",
        alpha=0.95,
    )
  return f_pts + t_pts + s_pts


def draw_partially_filled_prism(ax, l, w, h):
  col_f, col_t, col_s = "#48cae4", "#caf0f8", "#0077b6"
  edge_col = "#03045e"

  occupied = set()
  for x in range(l):
    for z in range(w):
      occupied.add((x, 0, z))
  for y in range(h):
    occupied.add((0, y, 0))

  sorted_cubes = sorted(list(occupied), key=lambda c: (-c[2], c[1], c[0]))
  for x, y, z in sorted_cubes:
    if (x, y, z - 1) not in occupied:
      f = [
          project_oblique(x, y, z),
          project_oblique(x + 1, y, z),
          project_oblique(x + 1, y + 1, z),
          project_oblique(x, y + 1, z),
      ]
      ax.add_patch(
          patches.Polygon(
              f, closed=True, facecolor=col_f, edgecolor=edge_col, lw=1.1
          )
      )
    if (x, y + 1, z) not in occupied:
      t = [
          project_oblique(x, y + 1, z),
          project_oblique(x + 1, y + 1, z),
          project_oblique(x + 1, y + 1, z + 1),
          project_oblique(x, y + 1, z + 1),
      ]
      ax.add_patch(
          patches.Polygon(
              t, closed=True, facecolor=col_t, edgecolor=edge_col, lw=1.1
          )
      )
    if (x + 1, y, z) not in occupied:
      s = [
          project_oblique(x + 1, y, z),
          project_oblique(x + 1, y, z + 1),
          project_oblique(x + 1, y + 1, z + 1),
          project_oblique(x + 1, y + 1, z),
      ]
      ax.add_patch(
          patches.Polygon(
              s, closed=True, facecolor=col_s, edgecolor=edge_col, lw=1.1
          )
      )

  wire_lines = [
      [(0, 0, 0), (l, 0, 0)],
      [(l, 0, 0), (l, h, 0)],
      [(l, h, 0), (0, h, 0)],
      [(0, h, 0), (0, 0, 0)],
      [(0, h, 0), (0, h, w)],
      [(l, h, 0), (l, h, w)],
      [(l, h, w), (0, h, w)],
      [(l, 0, 0), (l, 0, w)],
      [(l, 0, w), (l, h, w)],
  ]
  for p_start, p_end in wire_lines:
    ps, pe = project_oblique(*p_start), project_oblique(*p_end)
    ax.plot([ps[0], pe[0]], [ps[1], pe[1]], color="#0f172a", lw=2.2)

  all_corners = [
      project_oblique(x, y, z)
      for x in (0, l)
      for y in (0, h)
      for z in (0, w)
  ]
  xs, ys = [p[0] for p in all_corners], [p[1] for p in all_corners]
  ax.set_xlim(min(xs) - 1.0, max(xs) + 1.0)
  ax.set_ylim(min(ys) - 1.0, max(ys) + 1.0)
  ax.axis("off")


def draw_warehouse_building(ax, l1, h1, l2, h2, w):
  col_front_a, col_front_b = "#00a8cc", "#38bdf8"
  col_top, col_side = "#bbf2f6", "#0077b6"
  edge = "#042f2e"

  # Section A (Left Tall Block: Width l1=20, Height h1=50, Depth w=25)
  render_box(
      ax,
      0,
      0,
      0,
      l1,
      h1,
      w,
      col_front=col_front_a,
      col_top=col_top,
      col_side=col_side,
  )
  # Section B (Right Short Block: Width l2=30, Height h2=25, Depth w=50)
  render_box(
      ax,
      l1,
      0,
      0,
      l2,
      h2,
      50,
      col_front=col_front_b,
      col_top=col_top,
      col_side=col_side,
  )

  # Windows & Doors
  for wy in [h1 * 0.4, h1 * 0.7]:
    for wx in [l1 * 0.25, l1 * 0.65]:
      w_pts = [
          project_oblique(wx - 2, wy - 2, 0),
          project_oblique(wx + 2, wy - 2, 0),
          project_oblique(wx + 2, wy + 2, 0),
          project_oblique(wx - 2, wy + 2, 0),
      ]
      ax.add_patch(
          patches.Polygon(
              w_pts, closed=True, facecolor="#ffffff", edgecolor=edge, lw=1.2
          )
      )

  d_pts = [
      project_oblique(l1 * 0.45 - 2, 0, 0),
      project_oblique(l1 * 0.45 + 2, 0, 0),
      project_oblique(l1 * 0.45 + 2, h1 * 0.25, 0),
      project_oblique(l1 * 0.45 - 2, h1 * 0.25, 0),
  ]
  ax.add_patch(
      patches.Polygon(
          d_pts, closed=True, facecolor="#ffffff", edgecolor=edge, lw=1.2
      )
  )

  db_pts = [
      project_oblique(l1 + l2 * 0.65 - 1.5, 0, 0),
      project_oblique(l1 + l2 * 0.65 + 1.5, 0, 0),
      project_oblique(l1 + l2 * 0.65 + 1.5, h2 * 0.35, 0),
      project_oblique(l1 + l2 * 0.65 - 1.5, h2 * 0.35, 0),
  ]
  ax.add_patch(
      patches.Polygon(
          db_pts, closed=True, facecolor="#ffffff", edgecolor=edge, lw=1.2
      )
  )

  # PRECISELY POSITIONED WAREHOUSE LABELS MATCHING SCREENSHOT
  # 1. Left Block Height (50 ft)
  p_h_bot, p_h_top = project_oblique(0, 0, 0), project_oblique(0, h1, 0)
  ax.text(
      p_h_bot[0] - 3.2,
      (p_h_bot[1] + p_h_top[1]) / 2,
      f"{h1} ft",
      fontsize=11,
      fontweight="bold",
      color="#f8fafc",
      ha="right",
      va="center",
  )

  # 2. Left Block Width (20 ft) on bottom front edge
  p_w_l, p_w_r = project_oblique(0, 0, 0), project_oblique(l1, 0, 0)
  ax.text(
      (p_w_l[0] + p_w_r[0]) / 2,
      p_w_l[1] - 2.2,
      f"{l1} ft",
      fontsize=11,
      fontweight="bold",
      color="#f8fafc",
      ha="center",
      va="top",
  )

  # 3. Left Block Depth (25 ft) along top receding edge
  p_d_f, p_d_b = project_oblique(l1 // 2, h1, 0), project_oblique(l1 // 2, h1, w)
  ax.text(
      (p_d_f[0] + p_d_b[0]) / 2 + 1.5,
      (p_d_f[1] + p_d_b[1]) / 2 + 1.0,
      f"{w} ft",
      fontsize=11,
      fontweight="bold",
      color="#f8fafc",
      ha="center",
      va="bottom",
  )

  # 4. Right Block Depth (50 ft) along right receding edge
  p_sd_f, p_sd_b = project_oblique(l1 + l2, h2, 0), project_oblique(
      l1 + l2, h2, 50
  )
  ax.text(
      (p_sd_f[0] + p_sd_b[0]) / 2 + 3.5,
      (p_sd_f[1] + p_sd_b[1]) / 2,
      f"{50} ft",
      fontsize=11,
      fontweight="bold",
      color="#f8fafc",
      ha="left",
      va="center",
  )

  all_pts = [
      project_oblique(x, y, z)
      for x in (0, l1 + l2)
      for y in (0, h1)
      for z in (0, 50)
  ]
  xs, ys = [p[0] for p in all_pts], [p[1] for p in all_pts]
  ax.set_xlim(min(xs) - 8, max(xs) + 12)
  ax.set_ylim(min(ys) - 8, max(ys) + 8)
  ax.axis("off")


def draw_stacked_ratio_boxes(ax, la, wa, lb, wb):
  h_a, h_b = 5, 5
  render_box(
      ax,
      (lb - la) / 2,
      h_b,
      0,
      la,
      h_a,
      wa,
      col_front="#f59e0b",
      col_top="#fde68a",
      col_side="#d97706",
      label="A",
  )
  render_box(
      ax,
      0,
      0,
      0,
      lb,
      h_b,
      wb,
      col_front="#00a8cc",
      col_top="#bbf2f6",
      col_side="#0077b6",
      label="B",
  )

  p_top_l, p_top_r = project_oblique(
      (lb - la) / 2, h_b + h_a + 0.6, 0
  ), project_oblique((lb + la) / 2, h_b + h_a + 0.6, 0)
  ax.text(
      (p_top_l[0] + p_top_r[0]) / 2,
      p_top_l[1] + 0.4,
      f"{la} in.",
      fontsize=11,
      fontweight="bold",
      color="#f8fafc",
      ha="center",
  )

  p_bot_l, p_bot_r = project_oblique(0, -0.8, 0), project_oblique(lb, -0.8, 0)
  ax.text(
      (p_bot_l[0] + p_bot_r[0]) / 2,
      p_bot_l[1] - 0.4,
      f"{lb} in.",
      fontsize=11,
      fontweight="bold",
      color="#f8fafc",
      ha="center",
  )

  p_side_f, p_side_b = project_oblique(lb + 0.5, -0.5, 0), project_oblique(
      lb + 0.5, -0.5, wb
  )
  ax.text(
      p_side_f[0] + 0.6,
      (p_side_f[1] + p_side_b[1]) / 2,
      f"{wb} in.",
      fontsize=11,
      fontweight="bold",
      color="#f8fafc",
      ha="left",
  )

  p_ha_mid = project_oblique((lb + la) / 2 + 0.5, h_b + h_a / 2, 0)
  ax.text(
      p_ha_mid[0] + 0.4,
      p_ha_mid[1],
      "? in.",
      fontsize=11,
      fontweight="bold",
      color="#f59e0b",
      ha="left",
  )

  p_hb_mid = project_oblique(lb + 0.5, h_b / 2, 0)
  ax.text(
      p_hb_mid[0] + 0.4,
      p_hb_mid[1],
      "? in.",
      fontsize=11,
      fontweight="bold",
      color="#00a8cc",
      ha="left",
  )

  all_pts = [
      project_oblique(x, y, z)
      for x in (0, lb)
      for y in (0, h_a + h_b)
      for z in (0, wb)
  ]
  xs, ys = [p[0] for p in all_pts], [p[1] for p in all_pts]
  ax.set_xlim(min(xs) - 2.0, max(xs) + 3.0)
  ax.set_ylim(min(ys) - 2.0, max(ys) + 2.0)
  ax.axis("off")


def draw_unit_cube_stepped_solid(ax, l1, h1, l2, h2, w):
  col_f, col_t, col_s = "#48cae4", "#caf0f8", "#0077b6"
  edge_col = "#0f172a"
  occupied = set()
  for x in range(l1):
    for y in range(h1):
      for z in range(w):
        occupied.add((x, y, z))
  for x in range(l1, l1 + l2):
    for y in range(h2):
      for z in range(w):
        occupied.add((x, y, z))

  sorted_cubes = sorted(list(occupied), key=lambda c: (-c[2], c[1], c[0]))
  all_pts = []
  for x, y, z in sorted_cubes:
    if (x, y, z - 1) not in occupied:
      f = [
          project_oblique(x, y, z),
          project_oblique(x + 1, y, z),
          project_oblique(x + 1, y + 1, z),
          project_oblique(x, y + 1, z),
      ]
      ax.add_patch(
          patches.Polygon(
              f, closed=True, facecolor=col_f, edgecolor=edge_col, lw=1.2
          )
      )
      all_pts.extend(f)
    if (x, y + 1, z) not in occupied:
      t = [
          project_oblique(x, y + 1, z),
          project_oblique(x + 1, y + 1, z),
          project_oblique(x + 1, y + 1, z + 1),
          project_oblique(x, y + 1, z + 1),
      ]
      ax.add_patch(
          patches.Polygon(
              t, closed=True, facecolor=col_t, edgecolor=edge_col, lw=1.2
          )
      )
      all_pts.extend(t)
    if (x + 1, y, z) not in occupied:
      s = [
          project_oblique(x + 1, y, z),
          project_oblique(x + 1, y, z + 1),
          project_oblique(x + 1, y + 1, z + 1),
          project_oblique(x + 1, y + 1, z),
      ]
      ax.add_patch(
          patches.Polygon(
              s, closed=True, facecolor=col_s, edgecolor=edge_col, lw=1.2
          )
      )
      all_pts.extend(s)

  xs, ys = [p[0] for p in all_pts], [p[1] for p in all_pts]
  ax.set_xlim(min(xs) - 0.8, max(xs) + 0.8)
  ax.set_ylim(min(ys) - 0.8, max(ys) + 0.8)
  ax.axis("off")


def generate_diagram(diagram_type: str, params: dict) -> io.BytesIO:
  fig, ax = plt.subplots(figsize=(6.2, 3.8), dpi=140)
  if diagram_type == "partially_filled":
    draw_partially_filled_prism(ax, params["l"], params["w"], params["h"])
  elif diagram_type == "warehouse_building":
    draw_warehouse_building(
        ax,
        params["l1"],
        params["h1"],
        params["l2"],
        params["h2"],
        params["w"],
    )
  elif diagram_type == "stacked_ratio_boxes":
    draw_stacked_ratio_boxes(
        ax, params["la"], params["wa"], params["lb"], params["wb"]
    )
  elif diagram_type == "stepped_solid":
    draw_unit_cube_stepped_solid(
        ax,
        params["l1"],
        params["h1"],
        params["l2"],
        params["h2"],
        params["w"],
    )

  buf = io.BytesIO()
  plt.tight_layout()
  plt.savefig(buf, format="png", bbox_inches="tight", transparent=True)
  buf.seek(0)
  plt.close(fig)
  return buf


def helper_shuffle_options(correct_text, distractor_texts):
  opts = [correct_text] + distractor_texts
  random.shuffle(opts)
  return opts


def clean_math_string(s: str) -> str:
  s = str(s).strip().lower().replace(",", "")
  s = re.sub(
      r"\b(cubic\s+units?|cubic\s+inches?|cubic\s+feet?|cu\s+ft|cu\s+in|inches?|feet?|ft|in|cubes?|meters?|m)\b",
      "",
      s,
  )
  return s.strip()


def check_user_answer(user_input, q: dict) -> bool:
  if q.get("input_type") == "multiselect":
    return set(q.get("correct_answers", [])) == set(
        user_input if isinstance(user_input, list) else []
    )

  if q.get("input_type") == "multi_text":
    if not isinstance(user_input, dict):
      return False
    for k, acc_list in q.get("accepted_answers_dict", {}).items():
      val = clean_math_string(user_input.get(k, ""))
      acc_cleaned = [clean_math_string(a) for a in acc_list]
      if val not in acc_cleaned:
        matched = False
        try:
          u_float = float(eval(val))
          for a in acc_cleaned:
            if math.isclose(u_float, float(eval(a)), rel_tol=1e-4):
              matched = True
              break
        except:
          pass
        if not matched:
          return False
    return True

  if q.get("input_type") == "radio":
    return user_input == q["answer"]

  cleaned_user = clean_math_string(user_input)
  accepted = [clean_math_string(ans) for ans in q.get("accepted_answers", [])]
  if cleaned_user in accepted:
    return True
  try:
    user_num = float(eval(cleaned_user))
    for acc in accepted:
      if math.isclose(user_num, float(eval(acc)), rel_tol=1e-4):
        return True
  except:
    pass
  return False


# ==============================================================================
# 5. UNIT 2: VOLUME GENERATORS
# ==============================================================================
def gen_mh_u2_vocab_composite():
  correct = "composite solid"
  opts = helper_shuffle_options(
      correct, ["rectangular prism", "unit cube", "volume"]
  )
  return {
      "template_id": "mh_u2_vocab_composite",
      "topic": "Unit 2: Volume",
      "lesson": "Lesson 2-4",
      "input_type": "radio",
      "options": opts,
      "scenario": "Lesson 2-4: Complete the vocabulary sentence.",
      "question": (
          "A [ _____ ] is a solid figure that is made up of two or more solids."
      ),
      "answer": correct,
      "explanation": (
          "A **composite solid** is formed by combining two or more geometric"
          " solids."
      ),
  }


def gen_mh_u2_vocab_volume():
  correct = "volume"
  opts = helper_shuffle_options(
      correct, ["surface area", "perimeter", "capacity"]
  )
  return {
      "template_id": "mh_u2_vocab_volume",
      "topic": "Unit 2: Volume",
      "lesson": "Lesson 2-1",
      "input_type": "radio",
      "options": opts,
      "scenario": "Lesson 2-1: Complete the vocabulary sentence.",
      "question": (
          "The space occupied by a 3-dimensional figure, or solid figure, is"
          " called [ _____ ]."
      ),
      "answer": correct,
      "explanation": (
          "**Volume** measures the amount of 3D space contained inside a solid"
          " figure."
      ),
  }


def gen_mh_u2_vocab_unit_cube():
  correct = "unit cube"
  opts = helper_shuffle_options(
      correct, ["cubic unit", "rectangular prism", "face"]
  )
  return {
      "template_id": "mh_u2_vocab_unit_cube",
      "topic": "Unit 2: Volume",
      "lesson": "Lesson 2-1",
      "input_type": "radio",
      "options": opts,
      "scenario": "Lesson 2-1: Complete the vocabulary sentence.",
      "question": (
          "A cube with edge lengths of one unit is called a [ _____ ]."
      ),
      "answer": correct,
      "explanation": (
          "A cube where length, width, and height are each 1 unit is a **unit"
          " cube**."
      ),
  }


def gen_mh_u2_vocab_cubic_unit():
  correct = "cubic unit"
  opts = helper_shuffle_options(
      correct, ["square unit", "linear unit", "unit fraction"]
  )
  return {
      "template_id": "mh_u2_vocab_cubic_unit",
      "topic": "Unit 2: Volume",
      "lesson": "Lesson 2-2",
      "input_type": "radio",
      "options": opts,
      "scenario": "Lesson 2-2: Complete the vocabulary sentence.",
      "question": "A [ _____ ] is a unit for measuring volume.",
      "answer": correct,
      "explanation": (
          "Volume is measured in **cubic units** (e.g., cubic inches, cubic"
          " centimeters)."
      ),
  }


def gen_mh_u2_vocab_formula():
  correct = "formula"
  opts = helper_shuffle_options(correct, ["expression", "variable", "operation"])
  return {
      "template_id": "mh_u2_vocab_formula",
      "topic": "Unit 2: Volume",
      "lesson": "Lesson 2-3",
      "input_type": "radio",
      "options": opts,
      "scenario": "Lesson 2-3: Complete the vocabulary sentence.",
      "question": (
          "A [ _____ ] is an equation that describes the relationship between"
          " two or more quantities."
      ),
      "answer": correct,
      "explanation": (
          "A **formula** (like $V = l \\times w \\times h$) relates dimensions"
          " to volume."
      ),
  }


def gen_mh_u2_vocab_prism():
  correct = "rectangular prism"
  opts = helper_shuffle_options(correct, ["cube", "cylinder", "pyramid"])
  return {
      "template_id": "mh_u2_vocab_prism",
      "topic": "Unit 2: Volume",
      "lesson": "Lesson 2-1",
      "input_type": "radio",
      "options": opts,
      "scenario": "Lesson 2-1: Complete the vocabulary sentence.",
      "question": (
          "A 3-dimensional figure with six rectangular faces is called a"
          " [ _____ ]."
      ),
      "answer": correct,
      "explanation": (
          "A **rectangular prism** is bounded by 6 rectangular flat faces."
      ),
  }


def gen_mh_u2_target_volume_multiselect():
  target_vol = random.choice([24, 36, 48])
  options_data = [
      (
          f"Length = {target_vol // 6} units, Width = 3 units, Height = 2"
          " units",
          True,
      ),
      (
          f"Length = {target_vol // 4} units, Width = 2 units, Height = 2"
          " units",
          True,
      ),
      (
          f"Length = {target_vol // 2} units, Width = 1 unit, Height = 2 units",
          True,
      ),
      ("Length = 3 units, Width = 3 units, Height = 3 units", 27 == target_vol),
      ("Length = 5 units, Width = 2 units, Height = 4 units", 40 == target_vol),
      ("Length = 6 units, Width = 6 units, Height = 2 units", 72 == target_vol),
  ]
  random.shuffle(options_data)
  opts = [p[0] for p in options_data]
  correct_opts = [p[0] for p in options_data if p[1]]
  return {
      "template_id": "mh_u2_target_vol_multiselect",
      "topic": "Unit 2: Volume",
      "lesson": "Lesson 2-3",
      "input_type": "multiselect",
      "options": opts,
      "correct_answers": correct_opts,
      "scenario": "Lesson 2-3: Choose all that apply.",
      "question": (
          f"Which rectangular prisms have a volume of **{target_vol} cubic"
          " units**?"
      ),
      "explanation": (
          "Multiply length × width × height for each option. Options equaling"
          f" {target_vol} are correct."
      ),
  }


def gen_mh_u2_partially_filled_prism():
  l, w, h = (
      random.choice([3, 4, 5]),
      random.choice([2, 3]),
      random.choice([3, 4]),
  )
  total_vol = l * w * h
  return {
      "template_id": "mh_u2_partially_filled",
      "topic": "Unit 2: Volume",
      "lesson": "Lesson 2-2",
      "input_type": "text",
      "placeholder": "Enter number of cubic units (e.g., 24)",
      "diagram": "partially_filled",
      "diagram_params": {"l": l, "w": w, "h": h},
      "scenario": (
          "Lesson 2-2: The figure shows a rectangular prism partially filled"
          " with unit cubes."
      ),
      "question": (
          f"What is the volume of the rectangular prism? (Dimensions: {l} long,"
          f" {w} wide, {h} tall)"
      ),
      "answer": f"{total_vol} cubic units",
      "accepted_answers": [str(total_vol), f"{total_vol} cubic units"],
      "explanation": (
          f"The prism holds {l} cubes in length, {w} in width, and {h} in"
          f" height: {l} × {w} × {h} = **{total_vol} cubic units**."
      ),
  }


def gen_mh_u2_associative_property():
  l, w, h = random.randint(3, 5), random.randint(2, 4), random.randint(2, 4)
  correct = f"({l} × {w}) × {h} = {l} × ({w} × {h})"
  distractors = [
      f"({l} × {w}) × {h} = ({l} × {w}) + {h}",
      f"{l} × ({w} × {h}) = ({l} × {w}) × ({l} × {h})",
      f"{l} × ({w} + {h}) = ({l} × {w}) + ({l} × {h})",
  ]
  opts = helper_shuffle_options(correct, distractors)
  return {
      "template_id": "mh_u2_associative_property",
      "topic": "Unit 2: Volume",
      "lesson": "Lesson 2-3",
      "input_type": "radio",
      "options": opts,
      "scenario": "Lesson 2-3: Decomposing rectangular prisms into layers.",
      "question": (
          "Which equation represents the different ways to find the volume of a"
          f" prism measuring {l} units by {w} units by {h} units?"
      ),
      "answer": correct,
      "explanation": f"By the Associative Property of Multiplication: **{correct}**.",
  }


def gen_mh_u2_pool_depth_problem():
  length = random.choice([30, 40, 42])
  width = random.choice([12, 15, 20])
  wall_h = random.choice([5, 6])
  depth = wall_h - random.choice([1, 2])

  water_vol = length * width * depth
  pool_vol = length * width * wall_h

  correct = f"{water_vol:,} cubic feet"
  distractors = [
      f"{pool_vol:,} cubic feet",
      f"{length * width:,} cubic feet",
      f"{water_vol * 2:,} cubic feet",
  ]
  opts = helper_shuffle_options(correct, distractors)
  return {
      "template_id": "mh_u2_pool_depth",
      "topic": "Unit 2: Volume",
      "lesson": "Lesson 2-5",
      "input_type": "radio",
      "options": opts,
      "scenario": (
          f"A rectangular pool is {length} feet long, {width} feet wide, and"
          f" {wall_h} feet high. It is filled with water to a depth of {depth}"
          " feet."
      ),
      "question": "What is the volume of the water in the pool?",
      "answer": correct,
      "explanation": (
          f"Use the water's depth ({depth} ft), NOT the pool wall height"
          f" ({wall_h} ft)! Volume = {length} × {width} × {depth} = **{correct}**."
      ),
  }


def gen_mh_u2_dimensions_multiselect():
  target = random.choice([48, 60, 72])
  if target == 48:
    c1, c2 = (
        "length = 24 inches, width = 1 inch, height = 2 inches",
        "length = 12 inches, width = 2 inches, height = 2 inches",
    )
    w1, w2 = (
        "length = 6 inches, width = 6 inches, height = 4 inches",
        "length = 16 inches, width = 16 inches, height = 16 inches",
    )
  elif target == 60:
    c1, c2 = (
        "length = 10 inches, width = 3 inches, height = 2 inches",
        "length = 6 inches, width = 5 inches, height = 2 inches",
    )
    w1, w2 = (
        "length = 15 inches, width = 4 inches, height = 2 inches",
        "length = 4 inches, width = 4 inches, height = 4 inches",
    )
  else:
    c1, c2 = (
        "length = 12 inches, width = 3 inches, height = 2 inches",
        "length = 9 inches, width = 4 inches, height = 2 inches",
    )
    w1, w2 = (
        "length = 8 inches, width = 8 inches, height = 2 inches",
        "length = 10 inches, width = 7 inches, height = 1 inch",
    )

  pairs = [(c1, True), (c2, True), (w1, False), (w2, False)]
  random.shuffle(pairs)
  opts = [p[0] for p in pairs]
  corr = [p[0] for p in pairs if p[1]]
  return {
      "template_id": "mh_u2_dimensions_multiselect",
      "topic": "Unit 2: Volume",
      "lesson": "Lesson 2-3",
      "input_type": "multiselect",
      "options": opts,
      "correct_answers": corr,
      "scenario": (
          f"The volume of a rectangular prism is {target} cubic inches."
      ),
      "question": (
          "Which could be the dimensions of the prism? (Choose all that apply)"
      ),
      "explanation": (
          "Multiply length × width × height for each option. Those that equal"
          f" {target} cubic inches are valid."
      ),
  }


def gen_mh_u2_stepped_solid_volume():
  l1, h1 = random.choice([3, 4]), random.choice([2, 3])
  l2, h2 = random.choice([3, 4]), h1 + 1
  w = 2
  tot = (l1 * h1 * w) + (l2 * h2 * w)

  correct = f"{tot} cubic units"
  distractors = [
      f"{tot - 4} cubic units",
      f"{tot + 2} cubic units",
      f"{tot + 6} cubic units",
  ]
  opts = helper_shuffle_options(correct, distractors)
  return {
      "template_id": "mh_u2_stepped_solid",
      "topic": "Unit 2: Volume",
      "lesson": "Lesson 2-4",
      "input_type": "radio",
      "options": opts,
      "diagram": "stepped_solid",
      "diagram_params": {"l1": l1, "h1": h1, "l2": l2, "h2": h2, "w": w},
      "scenario": "Lesson 2-4: Composite solids made of unit cubes.",
      "question": "What is the volume of this figure?",
      "answer": correct,
      "explanation": (
          f"Left section: {l1} × {w} × {h1} = {l1*w*h1} cubes. Right section:"
          f" {l2} × {w} × {h2} = {l2*w*h2} cubes. Total = **{tot} cubic"
          " units**."
      ),
  }


def gen_mh_u2_warehouse_problem():
  tot = 62500
  correct = f"{tot:,} cubic feet"
  distractors = ["37,500 cubic feet", "87,500 cubic feet", "50,000 cubic feet"]
  opts = helper_shuffle_options(correct, distractors)
  return {
      "template_id": "mh_u2_warehouse",
      "topic": "Unit 2: Volume",
      "lesson": "Lesson 2-4",
      "input_type": "radio",
      "options": opts,
      "diagram": "warehouse_building",
      "diagram_params": {"l1": 20, "h1": 50, "l2": 30, "h2": 25, "w": 25},
      "scenario": "The figure shows the plans for a warehouse.",
      "question": "What will be the volume of the warehouse?",
      "answer": correct,
      "explanation": (
          "Section A: 20 ft wide × 25 ft deep × 50 ft high = 25,000 cu ft.\n"
          "Section B: 30 ft wide × 50 ft deep × 25 ft high = 37,500 cu ft.\n"
          "Total Volume = 25,000 + 37,500 = **62,500 cubic feet**."
      ),
  }


def gen_mh_u2_stacked_boxes_table():
  tot_vol = 270
  va = 90
  vb = 180
  ha = 5
  hb = 5
  return {
      "template_id": "mh_u2_stacked_boxes_table",
      "topic": "Unit 2: Volume",
      "lesson": "Lesson 2-4",
      "hint": (
          "Since Box B is twice the volume of Box A, divide the total 270 into"
          " 3 equal parts (1 part for A, 2 parts for B). Then find the missing"
          " height using Volume ÷ (Length × Width)."
      ),
      "input_type": "multi_text",
      "diagram": "stacked_ratio_boxes",
      "diagram_params": {"la": 3, "wa": 6, "lb": 6, "wb": 6},
      "scenario": (
          f"The combined volume of the two boxes shown is {tot_vol} cubic"
          " inches. Box A and Box B have the same height and the same 6-inch"
          " depth. Box B has twice the volume of Box A."
      ),
      "question": "Determine the height and volume of each box.",
      "blank_fields": [
          {
              "key": "ha",
              "label": "Box A Height (in.):",
              "placeholder": "Enter height in inches (e.g., 8)",
          },
          {
              "key": "va",
              "label": "Box A Volume (cubic in.):",
              "placeholder": "Enter volume in cu in (e.g., 120)",
          },
          {
              "key": "hb",
              "label": "Box B Height (in.):",
              "placeholder": "Enter height in inches (e.g., 4)",
          },
          {
              "key": "vb",
              "label": "Box B Volume (cubic in.):",
              "placeholder": "Enter volume in cu in (e.g., 240)",
          },
      ],
      "accepted_answers_dict": {
          "ha": [str(ha)],
          "va": [str(va)],
          "hb": [str(hb)],
          "vb": [str(vb)],
      },
      "explanation": (
          f"1. **Divide Volume by Ratios:** Box A is 1 part, Box B is 2 parts (3"
          f" total parts).\n   * Box A Volume = {tot_vol} ÷ 3 = **{va} cu in**\n"
          f"   * Box B Volume = {va} × 2 = **{vb} cu in**\n2. **Find Height:**\n"
          f"   * Box B Base Area = 6 in. × 6 in. = 36 sq in.\n   * Height = {vb}"
          f" ÷ 36 = **{hb} in.**\n   * Since both boxes share the same height,"
          f" Box A Height is also **{ha} in.**"
      ),
  }


# ==============================================================================
# 6. UNIT 3: PLACE VALUE & NUMBER RELATIONSHIPS GENERATORS
# ==============================================================================
def gen_mh_compare_digits_two_numbers():
  d = random.choice([4, 6, 7, 8, 9])
  num_a = random.randint(2, 5) * 100000 + d * 10000 + random.randint(100, 999)
  num_b = random.randint(1, 4) * 100000 + d * 1000 + random.randint(100, 999)

  q_text = (
      f"Which statement correctly compares values of the digit {d} in"
      f" **{num_a:,}** and **{num_b:,}**?"
  )
  correct = (
      f"The value of the digit {d} in {num_a:,} is 10 times the value of the"
      f" digit {d} in {num_b:,}."
  )
  distractors = [
      (
          f"The value of the digit {d} in {num_a:,} is 1/10 the value of the"
          f" digit {d} in {num_b:,}."
      ),
      (
          f"The value of the digit {d} in {num_a:,} is 10,000 times the value"
          f" of the digit {d} in {num_b:,}."
      ),
      (
          f"The value of the digit {d} in {num_a:,} is 100 times the value of"
          f" the digit {d} in {num_b:,}."
      ),
  ]
  opts = helper_shuffle_options(correct, distractors)
  return {
      "template_id": "mh_compare_digits_two_numbers",
      "topic": "Unit 3: Place Value and Number Relationships",
      "lesson": "Lesson 3-1",
      "hint": (
          f"Compare the positions: Find which place {d} is in for each number,"
          " and count how many steps separate them."
      ),
      "input_type": "radio",
      "options": opts,
      "scenario": (
          "Lesson 3-1: Understanding relationships between digits in different"
          " numbers."
      ),
      "question": q_text,
      "answer": correct,
      "explanation": (
          f"In {num_a:,}, the {d} is in the ten-thousands place (value:"
          f" {d*10000:,}). In {num_b:,}, the {d} is in the thousands place"
          f" (value: {d*1000:,}). Since {d*10000:,} = 10 × {d*1000:,}, it is"
          " **10 times the value**."
      ),
  }


def gen_mh_word_to_standard_fill():
  w = random.randint(21, 65)
  t = random.randint(1, 9)
  rem = random.randint(11, 29)
  h, th = rem // 10, rem % 10

  w_str = number_to_word_2digit(w)
  dec_str = f"{ONES_WORDS[t]} hundred {number_to_word_2digit(rem)} thousandths"
  full_word = f"{w_str} and {dec_str}"
  target_standard = f"{w}.{t}{h}{th}"

  return {
      "template_id": "mh_word_to_standard_fill",
      "topic": "Unit 3: Place Value and Number Relationships",
      "lesson": "Lesson 3-3",
      "hint": (
          "Remember that the word 'and' represents where the decimal point"
          " goes."
      ),
      "input_type": "text",
      "placeholder": "Enter standard decimal (e.g., 0.123)",
      "scenario": "Lesson 3-3: Converting decimal word forms to standard form.",
      "question": (
          f"Complete the sentence.\n\nIn standard form, the number"
          f" *{full_word}* is written as:"
      ),
      "answer": target_standard,
      "accepted_answers": [target_standard],
      "explanation": (
          f"*{w_str}* = {w}, *and* = decimal point, and *{dec_str}* = .{t}{h}{th}."
          f" Standard form = **{target_standard}**."
      ),
  }


def gen_mh_multiselect_comparisons():
  true_pairs = [
      ("0.49 < 0.5", True),
      ("0.019 < 0.09", True),
      ("0.28 < 0.3", True),
      ("0.075 < 0.7", True),
      ("0.304 > 0.333", False),
      ("0.08 > 0.81", False),
      ("0.111 < 0.11", False),
      ("0.68 = 0.068", False),
  ]
  sample = random.sample(true_pairs, 6)
  opts = [p[0] for p in sample]
  correct_opts = [p[0] for p in sample if p[1]]

  return {
      "template_id": "mh_multiselect_comparisons",
      "topic": "Unit 3: Place Value and Number Relationships",
      "lesson": "Lesson 3-4",
      "hint": (
          "Line up the decimal points and compare digits from left to right"
          " (tenths, then hundredths, then thousandths)."
      ),
      "input_type": "multiselect",
      "options": opts,
      "correct_answers": correct_opts,
      "scenario": (
          "Lesson 3-4: Choose all that apply. Determine which decimal"
          " comparisons are true."
      ),
      "question": "Which comparisons are *true*?",
      "explanation": (
          "Compare decimals place by place (tenths, then hundredths, then"
          f" thousandths). Correct statements: {', '.join(correct_opts)}."
      ),
  }


def gen_mh_dual_rounding_fill():
  w = random.choice([0, 1, 2, 4])
  t = random.randint(3, 8)
  h = random.randint(3, 8)
  th = random.choice([5, 6, 7, 8])

  val_str = f"{w}.{t}{h}{th}"
  d_val = Decimal(val_str)

  rnd_hundredth = str(d_val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
  rnd_tenth = str(d_val.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))

  return {
      "template_id": "mh_dual_rounding_fill",
      "topic": "Unit 3: Place Value and Number Relationships",
      "lesson": "Lesson 3-5",
      "hint": (
          "Find the rounding place, then look at the digit to its right: 5 or"
          " more rounds up, 4 or less stays the same."
      ),
      "input_type": "multi_text",
      "blank_fields": [
          {
              "key": "hundredth",
              "label": f"{val_str} rounded to the nearest hundredth is:",
              "placeholder": "Enter decimal to 2 places (e.g., 0.12)",
          },
          {
              "key": "tenth",
              "label": f"{val_str} rounded to the nearest tenth is:",
              "placeholder": "Enter decimal to 1 place (e.g., 0.1)",
          },
      ],
      "accepted_answers_dict": {
          "hundredth": [rnd_hundredth],
          "tenth": [rnd_tenth],
      },
      "scenario": "Lesson 3-5: Round decimals to different place value levels.",
      "question": "Complete each sentence.",
      "explanation": (
          f"For {val_str}:\n"
          f"• Hundredths: Look at the thousandths digit ({th}). Since {th} >= 5,"
          f" round up to **{rnd_hundredth}**.\n"
          f"• Tenths: Look at the hundredths digit ({h}). Rounding yields"
          f" **{rnd_tenth}**."
      ),
  }


def gen_mh_multiselect_rounding():
  base = round(random.choice([3.2, 5.4, 8.1, 9.3]), 1)
  c1 = round(base - 0.03 + random.uniform(0.001, 0.004), 3)
  c2 = round(base + 0.02 + random.uniform(0.001, 0.004), 3)
  c3 = round(base + 0.03, 2)
  w1 = round(base - 0.11, 2)
  w2 = round(base + 0.062, 3)
  w3 = round(base - 0.088, 3)

  options_pool = [
      (f"{c1:.3f}", True),
      (f"{c2:.3f}", True),
      (f"{c3:.2f}", True),
      (f"{w1:.2f}", False),
      (f"{w2:.3f}", False),
      (f"{w3:.3f}", False),
  ]
  random.shuffle(options_pool)

  opts = [p[0] for p in options_pool]
  correct_opts = [p[0] for p in options_pool if p[1]]

  return {
      "template_id": "mh_multiselect_rounding",
      "topic": "Unit 3: Place Value and Number Relationships",
      "lesson": "Lesson 3-5",
      "hint": (
          "Test each option individually: Look at its hundredths place digit to"
          " see if it rounds up or down."
      ),
      "input_type": "multiselect",
      "options": opts,
      "correct_answers": correct_opts,
      "scenario": (
          "Lesson 3-5: Choose all that apply. Identify numbers that round to a"
          " specified tenth."
      ),
      "question": (
          f"Which numbers round to **{base}** when rounded to the nearest"
          " tenth?"
      ),
      "explanation": (
          f"Numbers from {base-0.05} to {base+0.049} round to {base}. Correct"
          f" choices: {', '.join(correct_opts)}."
      ),
  }


def gen_mh_table_comparison():
  w = random.randint(320, 480)
  v1 = round(w + random.choice([0.25, 0.42, 0.65]), 2)
  v2 = round(w + random.choice([0.09, 0.18, 0.35]), 2)

  sym = ">" if v1 > v2 else ("<" if v1 < v2 else "=")
  table_data = {
      "School": ["Valley H.S.", "Eastside H.S."],
      "Length of Track (in meters)": [f"{v1:.2f}", f"{v2:.2f}"],
  }

  return {
      "template_id": "mh_table_comparison",
      "topic": "Unit 3: Place Value and Number Relationships",
      "lesson": "Lesson 3-4",
      "hint": (
          "Since the whole numbers are identical, compare the tenths digits"
          " first."
      ),
      "input_type": "text",
      "placeholder": "Type symbol: >, <, or =",
      "table": table_data,
      "scenario": (
          "The table shows the lengths of the tracks at Valley High School and"
          " Eastside High School."
      ),
      "question": "Write a comparison using >, <, or =.",
      "answer": sym,
      "accepted_answers": [sym, f"{v1} {sym} {v2}", f"{v1}{sym}{v2}"],
      "explanation": (
          f"{v1} is {sym} {v2} because at the tenths place, {str(v1)[4]} is"
          f" {'>' if sym=='>' else '<'} {str(v2)[4]}."
      ),
  }


def gen_mh_true_powers_statement():
  val = random.choice([2, 4, 5, 7])
  v_ones, v_tenths = val, round(val * 0.1, 1)
  v_hund, v_thou = round(val * 0.01, 2), round(val * 0.001, 3)

  correct = f"{v_hund} is 10 times {v_thou}"
  distractors = [
      f"{v_thou} is 10 times {v_hund}",
      f"{v_hund} is 1/10 of {v_thou}",
      f"{v_ones} is 1/10 of {v_tenths}",
  ]
  opts = helper_shuffle_options(correct, distractors)

  return {
      "template_id": "mh_true_powers_statement",
      "topic": "Unit 3: Place Value and Number Relationships",
      "lesson": "Lesson 3-2",
      "hint": (
          "Remember: A digit in one place is 10 times what it is in the place"
          " to its right."
      ),
      "input_type": "radio",
      "options": opts,
      "scenario": (
          "Lesson 3-2: Understanding 10 times and 1/10 of decimal relationships."
      ),
      "question": "Which of the following statements is *true*?",
      "answer": correct,
      "explanation": (
          f"{v_hund} is in the hundredths place, which is one place to the left"
          f" of {v_thou} (thousandths). Therefore, **{correct}**."
      ),
  }


def gen_mh_multiplier_fill_sentence():
  val = random.choice([3, 5, 7, 8])
  mode = random.choice(["ten_times", "one_tenth"])

  if mode == "ten_times":
    left, right = f"{val}", f"{val*0.1:.1f}"
    ans_text = "10 times"
    accepted = ["10 times", "10 times as much as", "10 x", "10x", "10"]
    q_str = f"Complete the sentence.\n\n**{left} is [_____] {right}.**"
    expl = f"{left} (ones) is 10 times greater than {right} (tenths)."
  else:
    left, right = f"{val*0.01:.2f}", f"{val*0.1:.1f}"
    ans_text = "1/10 of"
    accepted = ["1/10 of", "1/10", "one-tenth of", "one tenth of", "0.1 of"]
    q_str = f"Complete the sentence.\n\n**{left} is [_____] {right}.**"
    expl = (
        f"{left} (hundredths) is 1/10 of {right} (tenths) because it is one"
        " place to the right."
    )

  return {
      "template_id": f"mh_mult_fill_{mode}",
      "topic": "Unit 3: Place Value and Number Relationships",
      "lesson": "Lesson 3-2",
      "hint": (
          "Ask yourself: is the first number bigger (10 times) or smaller (1/10"
          " of) than the second number?"
      ),
      "input_type": "text",
      "placeholder": "Type '10 times' or '1/10 of'",
      "scenario": (
          "Type '10 times' or '1/10 of' to make the sentence mathematically"
          " true."
      ),
      "question": q_str,
      "answer": ans_text,
      "accepted_answers": accepted,
      "explanation": expl,
  }


def gen_mh_expanded_form_missing_terms():
  w, t, th = random.randint(3, 9), random.randint(2, 7), random.randint(3, 8)
  num_str = f"{w}.{t}0{th}"

  return {
      "template_id": "mh_expanded_missing_terms",
      "topic": "Unit 3: Place Value and Number Relationships",
      "lesson": "Lesson 3-3",
      "hint": (
          "Look at the place of each digit: tenths are multiplied by 1/10,"
          " hundredths by 1/100, and thousandths by 1/1,000."
      ),
      "input_type": "multi_text",
      "blank_fields": [
          {
              "key": "box1",
              "label": "First box (fractional place multiplier for tenths):",
              "placeholder": "Enter fractional unit (e.g., 1/10)",
          },
          {
              "key": "box2",
              "label": "Second box (digit in thousandths place):",
              "placeholder": "Enter single digit (e.g., 5)",
          },
      ],
      "accepted_answers_dict": {
          "box1": ["1/10", "0.1"],
          "box2": [str(th)],
      },
      "scenario": f"Complete the expanded form of the number {num_str}.",
      "question": f"**{w} + {t} × [ Box 1 ] + [ Box 2 ] × 1/1,000**",
      "explanation": (
          f"In {num_str}, {t} is in the tenths place ({t} × 1/10), and {th} is"
          f" in the thousandths place ({th} × 1/1,000)."
      ),
  }


def gen_mh_fraction_sum_to_standard():
  h, th = random.choice([2, 3, 5, 7]), random.choice([4, 6, 8, 9])
  std_ans = f"0.0{h}{th}"

  return {
      "template_id": "mh_frac_sum_to_std",
      "topic": "Unit 3: Place Value and Number Relationships",
      "lesson": "Lesson 3-3",
      "hint": (
          "Check which places are empty! If there are no tenths, place a 0 in"
          " the tenths place."
      ),
      "input_type": "text",
      "placeholder": "Enter decimal in standard form (e.g., 0.123)",
      "scenario": "Lesson 3-3: Write the decimal number in standard form.",
      "question": f"**{h} × 1/100 + {th} × 1/1,000**",
      "answer": std_ans,
      "accepted_answers": [std_ans, f".0{h}{th}"],
      "explanation": (
          f"{h} × 1/100 = 0.0{h} and {th} × 1/1,000 = 0.00{th}. Added together"
          f" = **{std_ans}**."
      ),
  }


def gen_mh_full_typed_word_form():
  w = random.randint(22, 58)
  t = random.randint(1, 9)
  rem = random.randint(11, 35)
  h, th = rem // 10, rem % 10

  w_str = number_to_word_2digit(w)
  dec_str = f"{ONES_WORDS[t]} hundred {number_to_word_2digit(rem)} thousandths"
  correct_word = f"{w_str} and {dec_str}"
  num_str = f"{w}.{t}{h}{th}"

  return {
      "template_id": "mh_typed_word_form",
      "topic": "Unit 3: Place Value and Number Relationships",
      "lesson": "Lesson 3-3",
      "hint": (
          "Write the whole number, write 'and' for the decimal point, then"
          " write the decimal digits followed by 'thousandths'."
      ),
      "input_type": "text",
      "placeholder": "Type words here (use hyphen if needed, e.g., twenty-one)",
      "scenario": "Lesson 3-3: Convert decimal numbers to words.",
      "question": f"Write **{num_str}** in **word form**:",
      "answer": correct_word,
      "accepted_answers": [correct_word, correct_word.replace("-", " ")],
      "explanation": (
          f"Read the whole number, use 'and' for decimal point, then read the"
          f" fractional part: **{correct_word}**."
      ),
  }


# ==============================================================================
# 7. UNITS 4 TO 7 GENERATORS
# ==============================================================================
def gen_add_sub_decimals():
  d1 = round(random.uniform(14.25, 48.75), 2)
  d2 = round(random.uniform(5.15, 18.50), 2)
  mode = random.choice(["add", "sub"])
  res = round(d1 + d2, 2) if mode == "add" else round(d1 - d2, 2)
  q_str = f"{d1:.2f} + {d2:.2f}" if mode == "add" else f"{d1:.2f} - {d2:.2f}"
  return {
      "template_id": "u4_decimals_ops_typed",
      "topic": "Unit 4: Add and Subtract Decimals",
      "hint": (
          "Line up the decimal points vertically before adding or subtracting."
      ),
      "input_type": "text",
      "placeholder": "Enter decimal result",
      "scenario": "Align decimal points vertically before adding or subtracting.",
      "question": f"Calculate: **{q_str}**",
      "answer": f"{res:.2f}",
      "accepted_answers": [f"{res:.2f}", str(res)],
      "explanation": f"Sum/Difference = **{res:.2f}**.",
  }


def gen_multiply_whole():
  n1, n2 = random.randint(120, 350), random.randint(12, 35)
  prod = n1 * n2
  return {
      "template_id": "u5_multiply_typed",
      "topic": "Unit 5: Multiply Multi-Digit Whole Numbers",
      "hint": (
          "Multiply by the ones place first, then put a 0 placeholder before"
          " multiplying by the tens digit."
      ),
      "input_type": "text",
      "placeholder": "Enter whole number product",
      "scenario": (
          f"A shipment has {n2} containers. Each container holds {n1} boxes."
      ),
      "question": (
          f"Calculate the total product: **{n1} × {n2}** (type your answer):"
      ),
      "answer": f"{prod:,}",
      "accepted_answers": [str(prod), f"{prod:,}"],
      "explanation": f"{n1} × {n2} = **{prod:,}**.",
  }


def gen_mult_div_decimals():
  fa, fb = round(random.uniform(2.1, 8.4), 1), round(
      random.uniform(0.3, 0.9), 1
  )
  prod = round(fa * fb, 2)
  opts = helper_shuffle_options(
      f"{prod:.2f}",
      [f"{prod * 10:.2f}", f"{prod / 10:.2f}", f"{prod + 0.2:.2f}"],
  )
  return {
      "template_id": "u6_mult_decimals",
      "topic": "Unit 6: Multiply Decimals",
      "hint": (
          "Multiply as if whole numbers, then count total decimal places (1 +"
          " 1 = 2) in the product."
      ),
      "input_type": "radio",
      "options": opts,
      "scenario": (
          "Count total decimal places in factors to place decimal point."
      ),
      "question": f"Multiply: **{fa} × {fb}**",
      "answer": f"{prod:.2f}",
      "explanation": f"{fa} × {fb} = **{prod:.2f}**.",
  }


def gen_divide_one_digit():
  div, quot, rem = (
      random.randint(4, 9),
      random.randint(35, 95),
      random.randint(1, 3),
  )
  total = (quot * div) + rem
  correct = f"{quot} R{rem}"
  return {
      "template_id": "u7_divide_one_digit_typed",
      "topic": "Unit 7: Divide Whole Numbers",
      "hint": "Divide step-by-step: Divide, Multiply, Subtract, Bring down.",
      "input_type": "text",
      "placeholder": "Format remainder as R (e.g., 12 R3)",
      "scenario": (
          f"{total} tickets are distributed evenly among {div} classrooms."
      ),
      "question": (
          f"Calculate: **{total} ÷ {div}** (format remainder as 'R', e.g.,"
          f" '12 R3'):"
      ),
      "answer": correct,
      "accepted_answers": [correct, f"{quot} r{rem}", f"{quot}r{rem}"],
      "explanation": f"{total} ÷ {div} = **{quot} R{rem}**.",
  }


def gen_divide_two_digit():
  divisor, quotient = random.randint(15, 32), random.randint(18, 45)
  dividend = divisor * quotient
  return {
      "template_id": "u7_divide_two_digit_typed",
      "topic": "Unit 7: Divide Whole Numbers",
      "hint": (
          "Estimate by rounding the divisor to the nearest ten to test"
          " quotient digits."
      ),
      "input_type": "text",
      "placeholder": "Enter whole number quotient",
      "scenario": (
          f"A warehouse packs {dividend} water bottles into cases of {divisor}."
      ),
      "question": f"What is **{dividend} ÷ {divisor}**?",
      "answer": str(quotient),
      "accepted_answers": [str(quotient)],
      "explanation": f"{dividend} ÷ {divisor} = **{quotient}**.",
  }


# ==============================================================================
# 8. MASTER GENERATOR REGISTRY
# ==============================================================================
GENERATORS = [
    # Unit 2: Volume Review Suite (14 McGraw-Hill Benchmark Items)
    gen_mh_u2_vocab_composite,
    gen_mh_u2_vocab_volume,
    gen_mh_u2_vocab_unit_cube,
    gen_mh_u2_vocab_cubic_unit,
    gen_mh_u2_vocab_formula,
    gen_mh_u2_vocab_prism,
    gen_mh_u2_target_volume_multiselect,
    gen_mh_u2_partially_filled_prism,
    gen_mh_u2_associative_property,
    gen_mh_u2_pool_depth_problem,
    gen_mh_u2_dimensions_multiselect,
    gen_mh_u2_stepped_solid_volume,
    gen_mh_u2_warehouse_problem,
    gen_mh_u2_stacked_boxes_table,
    # Unit 3: Place Value & Number Relationships
    gen_mh_compare_digits_two_numbers,
    gen_mh_word_to_standard_fill,
    gen_mh_multiselect_comparisons,
    gen_mh_dual_rounding_fill,
    gen_mh_multiselect_rounding,
    gen_mh_table_comparison,
    gen_mh_true_powers_statement,
    gen_mh_multiplier_fill_sentence,
    gen_mh_expanded_form_missing_terms,
    gen_mh_fraction_sum_to_standard,
    gen_mh_full_typed_word_form,
    # Unit 4: Add and Subtract Decimals
    gen_add_sub_decimals,
    # Unit 5: Multiply Multi-Digit Whole Numbers
    gen_multiply_whole,
    # Unit 6: Multiply Decimals
    gen_mult_div_decimals,
    # Unit 7: Divide Whole Numbers
    gen_divide_one_digit,
    gen_divide_two_digit,
]

TOPIC_TO_GENERATORS = {}
for g in GENERATORS:
  sample = g()
  TOPIC_TO_GENERATORS.setdefault(sample["topic"], []).append(g)

ALL_TOPICS = sorted(list(TOPIC_TO_GENERATORS.keys()))
init_db()

# ==============================================================================
# 9. STREAMLIT APPLICATION UI
# ==============================================================================
st.set_page_config(
    page_title="TN McGraw-Hill Math Prep", page_icon="📐", layout="wide"
)

for key in ["student", "current_q", "answered", "feedback"]:
  if key not in st.session_state:
    st.session_state[key] = None

for key in ["mastery", "recent_templates"]:
  if key not in st.session_state:
    st.session_state[key] = {} if key == "mastery" else []

if "q_counter" not in st.session_state:
  st.session_state.q_counter = 0

# --- Sidebar UI ---
with st.sidebar:
  st.header("👤 Student Profile")
  existing_students = list_students()
  profile_mode = st.radio(
      "Profile Action:",
      ["Select Existing Student", "Add New Student"],
      horizontal=True,
  )

  if profile_mode == "Select Existing Student":
    if existing_students:
      names = [s["name"] for s in existing_students]
      idx = (
          names.index(st.session_state.student["name"])
          if st.session_state.student
          else 0
      )
      chosen_name = st.selectbox("Choose Student:", names, index=idx)
      if st.button("Load Profile"):
        p = get_or_create_student(chosen_name)
        st.session_state.update({
            "student": p,
            "mastery": load_mastery(p["id"], ALL_TOPICS),
            "current_q": None,
            "recent_templates": [],
            "answered": False,
            "feedback": None,
        })
        st.rerun()
    else:
      st.info("No saved students found. Please choose 'Add New Student'.")
  else:
    new_name = st.text_input("New Student Name:")
    if st.button("Create & Start") and new_name.strip():
      p = get_or_create_student(new_name)
      st.session_state.update({
          "student": p,
          "mastery": load_mastery(p["id"], ALL_TOPICS),
          "current_q": None,
          "recent_templates": [],
          "answered": False,
          "feedback": None,
      })
      st.rerun()

  if st.session_state.student:
    st.caption(f"Active Student: **{st.session_state.student['name']}**")
    if st.button("🔄 Reset This Student to 0%", type="secondary"):
      reset_student_progress(st.session_state.student["id"], ALL_TOPICS)
      st.session_state.update({
          "mastery": {t: 0.0 for t in ALL_TOPICS},
          "recent_templates": [],
          "current_q": None,
          "answered": False,
          "feedback": None,
      })
      st.toast("Progress reset to 0%!", icon="🔄")
      st.rerun()

  st.markdown("---")
  selected_topics = st.multiselect(
      "🎯 Focus Units:",
      ALL_TOPICS,
      default=[
          "Unit 2: Volume"
          if "Unit 2: Volume" in ALL_TOPICS
          else ALL_TOPICS[0]
      ],
  )

  st.markdown("---")
  if st.session_state.student:
    st.header("📊 Unit Mastery")
    for topic in selected_topics:
      score = st.session_state.mastery.get(topic, 0.0)
      st.write(f"**{topic}** ({int(score * 100)}%)")
      st.progress(score)


# --- Question Dispatcher with Adaptive Teaching Prioritization ---
def pick_next_question():
  if not selected_topics:
    st.session_state.current_q = None
    return

  funcs = [f for t in selected_topics for f in TOPIC_TO_GENERATORS.get(t, [])]
  if not funcs:
    st.session_state.current_q = None
    return

  cooling = [
      f
      for f in funcs
      if f.__name__ not in st.session_state.recent_templates
  ]
  if not cooling:
    last = (
        st.session_state.recent_templates[-1]
        if st.session_state.recent_templates
        else None
    )
    cooling = [f for f in funcs if f.__name__ != last] or funcs
    st.session_state.recent_templates = []

  weights = []
  for f in cooling:
    dummy = f()
    score = st.session_state.mastery.get(dummy["topic"], 0.0)
    weights.append(max(0.1, 1.0 - score))

  chosen_func = random.choices(cooling, weights=weights, k=1)[0]
  st.session_state.current_q = chosen_func()
  st.session_state.answered = False
  st.session_state.feedback = None
  st.session_state.q_counter += 1

  st.session_state.recent_templates.append(chosen_func.__name__)
  max_buffer = max(1, len(funcs) - 1)
  if len(st.session_state.recent_templates) > min(6, max_buffer):
    st.session_state.recent_templates.pop(0)


# --- Main UI Area ---
st.title("📐 McGraw-Hill 5th Grade Math Prep")

if not st.session_state.student:
  st.info("👈 Select or create a student profile to begin.")
  st.stop()

if not selected_topics:
  st.warning("👈 Please select at least one unit.")
  st.stop()

if (
    st.session_state.current_q is None
    or st.session_state.current_q["topic"] not in selected_topics
):
  pick_next_question()

q = st.session_state.current_q
if q is None:
  st.warning("No questions available for the selected unit.")
  st.stop()

# ==============================================================================
# ADAPTIVE TEACHER INTERVENTION: TRIGGER MINI-LESSON ON LOW MASTERY (< 40%)
# ==============================================================================
current_topic_mastery = st.session_state.mastery.get(q["topic"], 0.0)

if current_topic_mastery < 0.40 and q["topic"] in MINI_LESSONS:
  lesson_info = MINI_LESSONS[q["topic"]]
  with st.expander(
      f"📖 **Teacher Mode Activated: {lesson_info['title']}** (Click to Review"
      " Concepts)",
      expanded=False,
  ):
    st.markdown(lesson_info["concept"])
    st.markdown("#### 📝 Worked Step-by-Step Example")
    st.info(lesson_info["example"])
    st.warning(f"⚠️ **Watch Out for This Common Mistake:** {lesson_info['trap']}")

lesson_badge = f" • *{q['lesson']}*" if "lesson" in q else ""
st.caption(f"Curriculum Unit: **{q['topic']}**{lesson_badge}")
st.info(f"**Context / Directions:**\n\n{q['scenario']}")

if "table" in q:
  st.write("**Reference Table:**")
  st.dataframe(pd.DataFrame(q["table"]), hide_index=True)

if "diagram" in q:
  img_buffer = generate_diagram(q["diagram"], q.get("diagram_params", {}))
  st.image(img_buffer, width=540)

if "hint" in q and not st.session_state.answered:
  with st.expander("💡 Need a Teacher Hint? Click here before answering!"):
    st.info(q["hint"])

st.write(f"### {q['question']}")

form_key = f"form_{q['template_id']}_{st.session_state.q_counter}"
with st.form(key=form_key):
  input_mode = q.get("input_type", "radio")
  user_response = None

  if input_mode == "radio":
    user_response = st.radio(
        "Choose the correct answer:",
        q["options"],
        index=None,
        disabled=st.session_state.answered,
    )

  elif input_mode == "multiselect":
    st.write("**Choose all that apply:**")
    selected_boxes = []
    for opt in q["options"]:
      if st.checkbox(opt, key=f"chk_{opt}_{st.session_state.q_counter}"):
        selected_boxes.append(opt)
    user_response = selected_boxes

  elif input_mode == "multi_text":
    user_response = {}
    for field in q["blank_fields"]:
      user_response[field["key"]] = st.text_input(
          field["label"],
          placeholder=field["placeholder"],
          disabled=st.session_state.answered,
          key=f"field_{field['key']}_{st.session_state.q_counter}",
      )

  else:
    user_response = st.text_input(
        "Fill in the blank:",
        placeholder=q.get("placeholder", "Type your answer here..."),
        disabled=st.session_state.answered,
    )

  submit = st.form_submit_button(
      "Check Answer", disabled=st.session_state.answered
  )

  if submit and not st.session_state.answered:
    has_input = False
    if input_mode == "multiselect":
      has_input = len(user_response) > 0
    elif input_mode == "multi_text":
      has_input = all(str(v).strip() != "" for v in user_response.values())
    elif user_response is not None and str(user_response).strip() != "":
      has_input = True

    if has_input:
      st.session_state.answered = True
      is_correct = check_user_answer(user_response, q)
      curr_score = st.session_state.mastery.get(q["topic"], 0.0)
      new_score = (
          min(1.0, curr_score + 0.15)
          if is_correct
          else max(0.0, curr_score - 0.20)
      )

      correct_ans_display = q.get("answer", "")
      if input_mode == "multiselect":
        correct_ans_display = ", ".join(q.get("correct_answers", []))
      elif input_mode == "multi_text":
        correct_ans_display = " | ".join(
            [f"{k}: {v[0]}" for k, v in q.get("accepted_answers_dict", {}).items()]
        )

      st.session_state.feedback = {
          "type": "success" if is_correct else "error",
          "msg": (
              f"🎉 **Correct!**\n\n{q['explanation']}"
              if is_correct
              else f"❌ **Not quite.**\n\n**Correct Answer:**"
              f" {correct_ans_display}\n\n💡 **Explanation:**"
              f" {q['explanation']}"
          ),
      }

      st.session_state.mastery[q["topic"]] = new_score
      record_attempt(
          st.session_state.student["id"],
          q["topic"],
          q["template_id"],
          is_correct,
          str(user_response),
          new_score,
      )

if st.session_state.feedback:
  if st.session_state.feedback["type"] == "success":
    st.success(st.session_state.feedback["msg"])
  else:
    st.error(st.session_state.feedback["msg"])

if st.session_state.answered and st.button("Next Question ➡️"):
  pick_next_question()
  st.rerun()
