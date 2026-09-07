# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "streamlit",
#   "pandas",
#   "matplotlib",
# ]
# ///

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import io
import math
import random
import re
import sqlite3
import matplotlib.patches as patches
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

# ==============================================================================
# 1. DATABASE SETUP & PERSISTENCE
# ==============================================================================
DB_FILE = "math_tutor.db"


def get_db():
  conn = sqlite3.connect(DB_FILE)
  conn.row_factory = sqlite3.Row
  return conn


def init_db():
  with get_db() as conn:
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS topic_mastery (
            student_id INTEGER,
            topic TEXT,
            mastery REAL DEFAULT 0.0,
            PRIMARY KEY (student_id, topic),
            FOREIGN KEY (student_id) REFERENCES students (id)
        )
        """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS attempt_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            topic TEXT,
            template_id TEXT,
            is_correct INTEGER,
            selected_answer TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students (id)
        )
        """)
    cursor.execute("PRAGMA table_info(attempt_logs)")
    if "template_id" not in [row["name"] for row in cursor.fetchall()]:
      cursor.execute("ALTER TABLE attempt_logs ADD COLUMN template_id TEXT")
    conn.commit()


def list_students():
  with get_db() as conn:
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM students ORDER BY name ASC")
    return [dict(row) for row in cursor.fetchall()]


def get_or_create_student(name: str):
  clean_name = name.strip().capitalize()
  if not clean_name:
    return None
  with get_db() as conn:
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM students WHERE name = ?", (clean_name,))
    row = cursor.fetchone()
    if row:
      return dict(row)
    cursor.execute("INSERT INTO students (name) VALUES (?)", (clean_name,))
    conn.commit()
    return {"id": cursor.lastrowid, "name": clean_name}


def load_mastery(student_id: int, all_topics: list[str]) -> dict[str, float]:
  with get_db() as conn:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT topic, mastery FROM topic_mastery WHERE student_id = ?",
        (student_id,),
    )
    mastery = {row["topic"]: row["mastery"] for row in cursor.fetchall()}
    for topic in all_topics:
      if topic not in mastery:
        mastery[topic] = 0.0
        cursor.execute(
            "INSERT INTO topic_mastery (student_id, topic, mastery) VALUES (?,"
            " ?, 0.0)",
            (student_id, topic),
        )
    conn.commit()
    return mastery


def reset_student_progress(student_id: int, all_topics: list[str]):
  with get_db() as conn:
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM attempt_logs WHERE student_id = ?", (student_id,)
    )
    for topic in all_topics:
      cursor.execute(
          """
            INSERT INTO topic_mastery (student_id, topic, mastery) VALUES (?, ?, 0.0)
            ON CONFLICT(student_id, topic) DO UPDATE SET mastery = 0.0
            """,
          (student_id, topic),
      )
    conn.commit()


def record_attempt(
    student_id: int,
    topic: str,
    template_id: str,
    is_correct: bool,
    selected_answer: str,
    new_mastery: float,
):
  with get_db() as conn:
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO attempt_logs (student_id, topic, template_id, is_correct, selected_answer)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            student_id,
            topic,
            template_id,
            1 if is_correct else 0,
            selected_answer,
        ),
    )
    cursor.execute(
        """
        INSERT INTO topic_mastery (student_id, topic, mastery) VALUES (?, ?, ?)
        ON CONFLICT(student_id, topic) DO UPDATE SET mastery = excluded.mastery
        """,
        (student_id, topic, new_mastery),
    )
    conn.commit()


# ==============================================================================
# 2. MINI-LESSON TEACHER REPOSITORY (MCGRAW-HILL LESSON ALIGNED)
# ==============================================================================
MINI_LESSONS = {
    "Unit 3: Place Value": {
        "title": "Unit 3: Place Value & Number Relationships",
        "concept": """
### 👩‍🏫 Lesson 3: Place Value & Decimal Power
* **10-to-1 Relationship:** Each place value is **10 times** greater than the place to its right, and **1/10** of the place to its left.
* **Tenths vs. Hundredths vs. Thousandths:**
  * Tenths: $0.1$ or $\\frac{1}{10}$ (1st digit right of decimal)
  * Hundredths: $0.01$ or $\\frac{1}{100}$ (2nd digit right of decimal)
  * Thousandths: $0.001$ or $\\frac{1}{1,000}$ (3rd digit right of decimal)
* **Rounding Decimals (Lesson 3-5):**
  1. Find the place you want to round to.
  2. Look at the digit directly to the right.
  3. If that digit is **5 or greater**, round up! If it is **4 or less**, keep it the same.
        """,
        "example": """
* **Word Form:** $44.259$ is read as *"forty-four and two hundred fifty-nine thousandths"*.
* **Rounding:** In $2.755$, to round to the nearest hundredth, look at the thousandths digit ($5$). Since $5 \\ge 5$, it rounds up to **$2.76$**.
        """,
        "trap": (
            "Don't confuse **Place** with **Value**! If a question asks for the"
            " *place*, answer with the name (*thousandths*). If it asks for the"
            " *value*, answer with the number (*0.009* or *9/1,000*)."
        ),
    },
    "Chapter 12: Geometry": {
        "title": "Unit 2 / Chapter 12: Volume of Compound Solids",
        "concept": """
### 👩‍🏫 Lesson: How to Find Volume of L-Shaped Solids
* **Formula:** $\\text{Volume} = \\text{Length} \\times \\text{Width} \\times \\text{Height}$ ($V = l \\times w \\times h$).
* **Additive Volume Strategy:**
  1. Split the irregular $L$-shape into two separate blocks: **Prism 1** and **Prism 2**.
  2. Find the dimensions ($l, w, h$) of Prism 1 and multiply them.
  3. Find the dimensions ($l, w, h$) of Prism 2 and multiply them.
  4. **Add both volumes together** to get the total volume!
        """,
        "example": (
            "If Prism 1 is $4 \\times 3 \\times 10 = 120$ cu in, and Prism 2"
            " is $6 \\times 3 \\times 4 = 72$ cu in:\n$$\\text{Total Volume} ="
            " 120 + 72 = 192 \\text{ cu in}$$\n"
        ),
        "trap": (
            "Make sure you don't use the total width or height twice! When you"
            " split the shape, break down the side that was cut."
        ),
    },
    "Chapter 2: Multiply Whole Numbers": {
        "title": "Chapter 2: Multi-Digit Multiplication",
        "concept": """
### 👩‍🏫 Lesson: Multi-Digit Multiplication
* Break multi-digit numbers down by place value or use the standard algorithm:
  1. Multiply by the ones digit.
  2. Place a **0 placeholder** before multiplying by the tens digit.
  3. Add both partial products together.
        """,
        "example": (
            "To multiply $142 \\times 23$:\n* $142 \\times 3 = 426$\n* $142"
            " \\times 20 = 2,840$\n* $426 + 2,840 = 3,266$."
        ),
        "trap": (
            "Don't forget the zero placeholder when multiplying by the tens"
            " digit!"
        ),
    },
}

# ==============================================================================
# 3. 3D VISUAL ENGINE & DECOMPOSITION GENERATOR
# ==============================================================================


def draw_dim_line(ax, p1, p2, text, offset=(0, 0), ha="center", va="center"):
  ax.plot(
      [p1[0], p2[0]],
      [p1[1], p2[1]],
      color="#38bdf8",
      lw=1.8,
      marker="|",
      markersize=8,
      markeredgewidth=2,
  )
  mid_x = (p1[0] + p2[0]) / 2 + offset[0]
  mid_y = (p1[1] + p2[1]) / 2 + offset[1]
  bbox = dict(
      boxstyle="round,pad=0.25",
      facecolor="#0f172a",
      edgecolor="#38bdf8",
      lw=1.4,
  )
  ax.text(
      mid_x,
      mid_y,
      text,
      color="#f8fafc",
      fontsize=10,
      fontweight="bold",
      ha=ha,
      va=va,
      bbox=bbox,
  )


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
          f_pts, closed=True, facecolor=col_front, edgecolor=edge_col, lw=1.8
      )
  )
  ax.add_patch(
      patches.Polygon(
          t_pts, closed=True, facecolor=col_top, edgecolor=edge_col, lw=1.8
      )
  )
  ax.add_patch(
      patches.Polygon(
          s_pts, closed=True, facecolor=col_side, edgecolor=edge_col, lw=1.8
      )
  )

  if label:
    cx = x0 + lx / 2
    cy = y0 + ly / 2
    px, py = project_oblique(cx, cy, z0)
    ax.text(
        px,
        py,
        label,
        fontsize=24,
        fontweight="bold",
        color="white",
        ha="center",
        va="center",
        alpha=0.9,
    )

  return f_pts + t_pts + s_pts


def draw_compound_l_prism(ax, l1, h1, l2, h2, w):
  col_front, col_top, col_side = "#00a8cc", "#bbf2f6", "#006a8e"
  edge_col = "#042f2e"

  front_poly = [
      project_oblique(0, 0, 0),
      project_oblique(l1 + l2, 0, 0),
      project_oblique(l1 + l2, h2, 0),
      project_oblique(l1, h2, 0),
      project_oblique(l1, h1, 0),
      project_oblique(0, h1, 0),
  ]
  ax.add_patch(
      patches.Polygon(
          front_poly,
          closed=True,
          facecolor=col_front,
          edgecolor=edge_col,
          lw=2.2,
      )
  )

  top_tall = [
      project_oblique(0, h1, 0),
      project_oblique(l1, h1, 0),
      project_oblique(l1, h1, w),
      project_oblique(0, h1, w),
  ]
  top_step = [
      project_oblique(l1, h2, 0),
      project_oblique(l1 + l2, h2, 0),
      project_oblique(l1 + l2, h2, w),
      project_oblique(l1, h2, w),
  ]
  ax.add_patch(
      patches.Polygon(
          top_tall, closed=True, facecolor=col_top, edgecolor=edge_col, lw=2.2
      )
  )
  ax.add_patch(
      patches.Polygon(
          top_step, closed=True, facecolor=col_top, edgecolor=edge_col, lw=2.2
      )
  )

  side_right = [
      project_oblique(l1 + l2, 0, 0),
      project_oblique(l1 + l2, h2, 0),
      project_oblique(l1 + l2, h2, w),
      project_oblique(l1 + l2, 0, w),
  ]
  side_step_inner = [
      project_oblique(l1, h2, 0),
      project_oblique(l1, h1, 0),
      project_oblique(l1, h1, w),
      project_oblique(l1, h2, w),
  ]
  ax.add_patch(
      patches.Polygon(
          side_right, closed=True, facecolor=col_side, edgecolor=edge_col, lw=2.2
      )
  )
  ax.add_patch(
      patches.Polygon(
          side_step_inner,
          closed=True,
          facecolor=col_side,
          edgecolor=edge_col,
          lw=2.0,
      )
  )

  p1_h1, p2_h1 = project_oblique(-1.0, 0, 0), project_oblique(-1.0, h1, 0)
  draw_dim_line(ax, p1_h1, p2_h1, f"{h1} in", offset=(-0.5, 0), ha="right")

  p1_base, p2_base = project_oblique(0, -1.0, 0), project_oblique(
      l1 + l2, -1.0, 0
  )
  draw_dim_line(
      ax, p1_base, p2_base, f"{l1 + l2} in", offset=(0, -0.5), ha="center"
  )

  p1_top, p2_top = project_oblique(0, h1 + 1.0, 0), project_oblique(
      l1, h1 + 1.0, 0
  )
  draw_dim_line(ax, p1_top, p2_top, f"{l1} in", offset=(0, 0.4), ha="center")

  p1_h2, p2_h2 = project_oblique(l1 + l2 + 1.0, 0, 0), project_oblique(
      l1 + l2 + 1.0, h2, 0
  )
  draw_dim_line(ax, p1_h2, p2_h2, f"{h2} in", offset=(0.5, 0), ha="left")

  p1_depth = project_oblique(l1 + l2 + 0.6, -0.6, 0)
  p2_depth = project_oblique(l1 + l2 + 0.6, -0.6, w)
  draw_dim_line(
      ax, p1_depth, p2_depth, f"{w} in", offset=(0.7, -0.2), ha="left"
  )

  all_pts = (
      front_poly
      + top_tall
      + top_step
      + side_right
      + [p1_h1, p2_h1, p1_base, p2_base, p1_top, p2_top, p1_depth, p2_depth]
  )
  xs = [pt[0] for pt in all_pts]
  ys = [pt[1] for pt in all_pts]
  ax.set_xlim(min(xs) - 1.5, max(xs) + 1.5)
  ax.set_ylim(min(ys) - 1.5, max(ys) + 1.5)
  ax.axis("off")


def draw_compound_l_breakdown(ax, l1, h1, l2, h2, w):
  gap = 4.0
  pts = []

  pts += render_box(
      ax,
      0,
      0,
      0,
      l1,
      h1,
      w,
      col_front="#2563eb",
      col_top="#93c5fd",
      col_side="#1d4ed8",
      label="1",
  )
  p_l1_b = project_oblique(0, -0.8, 0)
  p_l1_e = project_oblique(l1, -0.8, 0)
  draw_dim_line(ax, p_l1_b, p_l1_e, f"{l1} in", offset=(0, -0.4), ha="center")

  p_h1_b = project_oblique(-0.8, 0, 0)
  p_h1_e = project_oblique(-0.8, h1, 0)
  draw_dim_line(ax, p_h1_b, p_h1_e, f"{h1} in", offset=(-0.4, 0), ha="right")

  p_w1_b = project_oblique(l1 + 0.4, -0.4, 0)
  p_w1_e = project_oblique(l1 + 0.4, -0.4, w)
  draw_dim_line(ax, p_w1_b, p_w1_e, f"{w} in", offset=(0.5, -0.2), ha="left")

  x2 = l1 + gap
  pts += render_box(
      ax,
      x2,
      0,
      0,
      l2,
      h2,
      w,
      col_front="#059669",
      col_top="#6ee7b7",
      col_side="#047857",
      label="2",
  )
  p_l2_b = project_oblique(x2, -0.8, 0)
  p_l2_e = project_oblique(x2 + l2, -0.8, 0)
  draw_dim_line(ax, p_l2_b, p_l2_e, f"{l2} in", offset=(0, -0.4), ha="center")

  p_h2_b = project_oblique(x2 + l2 + 0.8, 0, 0)
  p_h2_e = project_oblique(x2 + l2 + 0.8, h2, 0)
  draw_dim_line(ax, p_h2_b, p_h2_e, f"{h2} in", offset=(0.5, 0), ha="left")

  p_w2_b = project_oblique(x2 + l2 + 0.4, -0.4, 0)
  p_w2_e = project_oblique(x2 + l2 + 0.4, -0.4, w)
  draw_dim_line(ax, p_w2_b, p_w2_e, f"{w} in", offset=(0.5, -0.2), ha="left")

  xs = [pt[0] for pt in pts]
  ys = [pt[1] for pt in pts]
  ax.set_xlim(min(xs) - 2.0, max(xs) + 2.0)
  ax.set_ylim(min(ys) - 1.8, max(ys) + 1.8)
  ax.axis("off")


def draw_unit_cubes_compound(ax, l1, h1, l2, h2, w):
  col_front, col_top, col_side = "#38bdf8", "#bae6fd", "#0284c7"
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
      f_pts = [
          project_oblique(x, y, z),
          project_oblique(x + 1, y, z),
          project_oblique(x + 1, y + 1, z),
          project_oblique(x, y + 1, z),
      ]
      ax.add_patch(
          patches.Polygon(
              f_pts,
              closed=True,
              facecolor=col_front,
              edgecolor=edge_col,
              lw=1.2,
          )
      )
      all_pts.extend(f_pts)
    if (x, y + 1, z) not in occupied:
      t_pts = [
          project_oblique(x, y + 1, z),
          project_oblique(x + 1, y + 1, z),
          project_oblique(x + 1, y + 1, z + 1),
          project_oblique(x, y + 1, z + 1),
      ]
      ax.add_patch(
          patches.Polygon(
              t_pts, closed=True, facecolor=col_top, edgecolor=edge_col, lw=1.2
          )
      )
      all_pts.extend(t_pts)
    if (x + 1, y, z) not in occupied:
      r_pts = [
          project_oblique(x + 1, y, z),
          project_oblique(x + 1, y, z + 1),
          project_oblique(x + 1, y + 1, z + 1),
          project_oblique(x + 1, y + 1, z),
      ]
      ax.add_patch(
          patches.Polygon(
              r_pts, closed=True, facecolor=col_side, edgecolor=edge_col, lw=1.2
          )
      )
      all_pts.extend(r_pts)

  xs = [pt[0] for pt in all_pts]
  ys = [pt[1] for pt in all_pts]
  ax.set_xlim(min(xs) - 1.0, max(xs) + 1.0)
  ax.set_ylim(min(ys) - 1.0, max(ys) + 1.0)
  ax.axis("off")


def draw_unit_cubes_breakdown(ax, l1, h1, l2, h2, w):
  edge_col = "#0f172a"
  gap_x = 2
  occupied = set()

  for x in range(l1):
    for y in range(h1):
      for z in range(w):
        occupied.add((x, y, z, 1))

  for x in range(l1 + gap_x, l1 + gap_x + l2):
    for y in range(h2):
      for z in range(w):
        occupied.add((x, y, z, 2))

  sorted_cubes = sorted(list(occupied), key=lambda c: (-c[2], c[1], c[0]))
  all_pts = []

  for x, y, z, grp in sorted_cubes:
    col_front = "#2563eb" if grp == 1 else "#059669"
    col_top = "#93c5fd" if grp == 1 else "#6ee7b7"
    col_side = "#1d4ed8" if grp == 1 else "#047857"

    if not any(
        c[0] == x and c[1] == y and c[2] == z - 1 and c[3] == grp
        for c in occupied
    ):
      f_pts = [
          project_oblique(x, y, z),
          project_oblique(x + 1, y, z),
          project_oblique(x + 1, y + 1, z),
          project_oblique(x, y + 1, z),
      ]
      ax.add_patch(
          patches.Polygon(
              f_pts,
              closed=True,
              facecolor=col_front,
              edgecolor=edge_col,
              lw=1.2,
          )
      )
      all_pts.extend(f_pts)

    if not any(
        c[0] == x and c[1] == y + 1 and c[2] == z and c[3] == grp
        for c in occupied
    ):
      t_pts = [
          project_oblique(x, y + 1, z),
          project_oblique(x + 1, y + 1, z),
          project_oblique(x + 1, y + 1, z + 1),
          project_oblique(x, y + 1, z + 1),
      ]
      ax.add_patch(
          patches.Polygon(
              t_pts, closed=True, facecolor=col_top, edgecolor=edge_col, lw=1.2
          )
      )
      all_pts.extend(t_pts)

    if not any(
        c[0] == x + 1 and c[1] == y and c[2] == z and c[3] == grp
        for c in occupied
    ):
      r_pts = [
          project_oblique(x + 1, y, z),
          project_oblique(x + 1, y, z + 1),
          project_oblique(x + 1, y + 1, z + 1),
          project_oblique(x + 1, y + 1, z),
      ]
      ax.add_patch(
          patches.Polygon(
              r_pts, closed=True, facecolor=col_side, edgecolor=edge_col, lw=1.2
          )
      )
      all_pts.extend(r_pts)

  p1_lbl = project_oblique(l1 / 2, -0.6, 0)
  ax.text(
      p1_lbl[0],
      p1_lbl[1],
      f"Prism 1\n({l1 * h1 * w} cubes)",
      color="#93c5fd",
      fontsize=11,
      fontweight="bold",
      ha="center",
  )
  p2_lbl = project_oblique(l1 + gap_x + l2 / 2, -0.6, 0)
  ax.text(
      p2_lbl[0],
      p2_lbl[1],
      f"Prism 2\n({l2 * h2 * w} cubes)",
      color="#6ee7b7",
      fontsize=11,
      fontweight="bold",
      ha="center",
  )

  xs = [pt[0] for pt in all_pts]
  ys = [pt[1] for pt in all_pts]
  ax.set_xlim(min(xs) - 1.0, max(xs) + 1.0)
  ax.set_ylim(min(ys) - 1.5, max(ys) + 1.0)
  ax.axis("off")


def draw_fraction_area(ax, num, den):
  bar_width = 8.0
  box_width = bar_width / den
  for i in range(den):
    color = "#2ecc71" if i < num else "#334155"
    rect = patches.Rectangle(
        (i * box_width, 0.5),
        box_width,
        1.8,
        facecolor=color,
        edgecolor="#f8fafc",
        lw=2,
    )
    ax.add_patch(rect)

  bbox = dict(
      boxstyle="round,pad=0.3",
      facecolor="#0f172a",
      edgecolor="#38bdf8",
      lw=1.2,
  )
  ax.text(
      bar_width / 2,
      -0.4,
      f"Visual Model: {num}/{den}",
      ha="center",
      fontweight="bold",
      fontsize=12,
      color="#f8fafc",
      bbox=bbox,
  )
  ax.set_xlim(-0.5, bar_width + 0.5)
  ax.set_ylim(-0.9, 2.8)
  ax.axis("off")


def generate_diagram(diagram_type: str, params: dict) -> io.BytesIO:
  fig, ax = plt.subplots(figsize=(6.5, 4.2), dpi=140)
  if diagram_type == "compound_l_prism":
    draw_compound_l_prism(
        ax,
        params["l1"],
        params["h1"],
        params["l2"],
        params["h2"],
        params["w"],
    )
  elif diagram_type == "compound_l_breakdown":
    draw_compound_l_breakdown(
        ax,
        params["l1"],
        params["h1"],
        params["l2"],
        params["h2"],
        params["w"],
    )
  elif diagram_type == "unit_cubes_compound":
    draw_unit_cubes_compound(
        ax,
        params["l1"],
        params["h1"],
        params["l2"],
        params["h2"],
        params["w"],
    )
  elif diagram_type == "unit_cubes_breakdown":
    draw_unit_cubes_breakdown(
        ax,
        params["l1"],
        params["h1"],
        params["l2"],
        params["h2"],
        params["w"],
    )
  elif diagram_type == "fraction_bar":
    draw_fraction_area(ax, params["num"], params["den"])

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
  s = str(s).strip().lower()
  s = s.replace(",", "")
  s = re.sub(
      r"\b(cubic\s+units?|cubic\s+inches?|cu\s+in|inches?|in|cubes?|meters?|m)\b",
      "",
      s,
  )
  s = s.strip()
  return s


def check_user_answer(user_input, q: dict) -> bool:
  if q.get("input_type") == "multiselect":
    correct_set = set(q.get("correct_answers", []))
    user_set = set(user_input if isinstance(user_input, list) else [])
    return correct_set == user_set

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
            try:
              if math.isclose(u_float, float(eval(a)), rel_tol=1e-4):
                matched = True
                break
            except:
              pass
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
      try:
        acc_num = float(eval(acc))
        if math.isclose(user_num, acc_num, rel_tol=1e-4):
          return True
      except:
        pass
  except:
    pass

  return False


# ==============================================================================
# 4. UNIT 3: PLACE VALUE GENERATORS (MCGRAW-HILL BENCHMARKS)
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


# --- Item 7: Comparing digit values across two large numbers (Lesson 3-1) ---
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
      "topic": "Unit 3: Place Value",
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


# --- Item 8: Standard form from word form (Lesson 3-3) ---
def gen_mh_word_to_standard_fill():
  w = random.randint(21, 65)
  t = random.randint(1, 9)
  rem = random.randint(11, 29)
  h = rem // 10
  th = rem % 10

  w_str = number_to_word_2digit(w)
  dec_str = f"{ONES_WORDS[t]} hundred {number_to_word_2digit(rem)} thousandths"
  full_word = f"{w_str} and {dec_str}"
  target_standard = f"{w}.{t}{h}{th}"

  return {
      "template_id": "mh_word_to_standard_fill",
      "topic": "Unit 3: Place Value",
      "lesson": "Lesson 3-3",
      "hint": (
          "Remember that the word 'and' represents where the decimal point"
          " goes."
      ),
      "input_type": "text",
      "placeholder": "Enter standard form (e.g., 0.123)",
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


# --- Item 9: Multi-Select True Comparisons (Lesson 3-4) ---
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
      "topic": "Unit 3: Place Value",
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


# --- Item 10: Dual-Blank Rounding with Decimal Round Half-Up (Lesson 3-5) ---
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
      "topic": "Unit 3: Place Value",
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


# --- Item 11: Multi-Select Rounding Target (Lesson 3-5) ---
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
      "topic": "Unit 3: Place Value",
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


# --- Item 12: Data Table Decimal Comparison (Lesson 3-4) ---
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
      "topic": "Unit 3: Place Value",
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
      "accepted_answers": [
          sym,
          f"{v1} {sym} {v2}",
          f"{v1}{sym}{v2}",
      ],
      "explanation": (
          f"{v1} is {sym} {v2} because at the tenths place, {str(v1)[4]} is"
          f" {'>' if sym=='>' else '<'} {str(v2)[4]}."
      ),
  }


# --- Item 13: True statements comparing 10 times and 1/10 (Lesson 3-2) ---
def gen_mh_true_powers_statement():
  val = random.choice([2, 4, 5, 7])
  v_ones = val
  v_tenths = round(val * 0.1, 1)
  v_hund = round(val * 0.01, 2)
  v_thou = round(val * 0.001, 3)

  correct = f"{v_hund} is 10 times {v_thou}"
  distractors = [
      f"{v_thou} is 10 times {v_hund}",
      f"{v_hund} is 1/10 of {v_thou}",
      f"{v_ones} is 1/10 of {v_tenths}",
  ]
  opts = helper_shuffle_options(correct, distractors)

  return {
      "template_id": "mh_true_powers_statement",
      "topic": "Unit 3: Place Value",
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


# --- Items 14 & 15: Sentence Fill-in Multiplier (Lesson 3-2) ---
def gen_mh_multiplier_fill_sentence():
  val = random.choice([3, 5, 7, 8])
  mode = random.choice(["ten_times", "one_tenth"])

  if mode == "ten_times":
    left = f"{val}"
    right = f"{val*0.1:.1f}"
    ans_text = "10 times"
    accepted = ["10 times", "10 times as much as", "10 x", "10x", "10"]
    q_str = f"Complete the sentence.\n\n**{left} is [_____] {right}.**"
    expl = f"{left} (ones) is 10 times greater than {right} (tenths)."
  else:
    left = f"{val*0.01:.2f}"
    right = f"{val*0.1:.1f}"
    ans_text = "1/10 of"
    accepted = ["1/10 of", "1/10", "one-tenth of", "one tenth of", "0.1 of"]
    q_str = f"Complete the sentence.\n\n**{left} is [_____] {right}.**"
    expl = (
        f"{left} (hundredths) is 1/10 of {right} (tenths) because it is one"
        " place to the right."
    )

  return {
      "template_id": f"mh_mult_fill_{mode}",
      "topic": "Unit 3: Place Value",
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


# --- Item 16: Fill-in Missing Terms of Expanded Form (Lesson 3-3) ---
def gen_mh_expanded_form_missing_terms():
  w = random.randint(3, 9)
  t = random.randint(2, 7)
  th = random.randint(3, 8)
  num_str = f"{w}.{t}0{th}"

  return {
      "template_id": "mh_expanded_missing_terms",
      "topic": "Unit 3: Place Value",
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


# --- Item 17: Sum of fraction products to standard form (Lesson 3-3) ---
def gen_mh_fraction_sum_to_standard():
  h = random.choice([2, 3, 5, 7])
  th = random.choice([4, 6, 8, 9])
  std_ans = f"0.0{h}{th}"

  return {
      "template_id": "mh_frac_sum_to_std",
      "topic": "Unit 3: Place Value",
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


# --- Item 18: Full Typed Word Form (Lesson 3-3) ---
def gen_mh_full_typed_word_form():
  w = random.randint(22, 58)
  t = random.randint(1, 9)
  rem = random.randint(11, 35)
  h = rem // 10
  th = rem % 10

  w_str = number_to_word_2digit(w)
  dec_str = f"{ONES_WORDS[t]} hundred {number_to_word_2digit(rem)} thousandths"
  correct_word = f"{w_str} and {dec_str}"
  num_str = f"{w}.{t}{h}{th}"

  return {
      "template_id": "mh_typed_word_form",
      "topic": "Unit 3: Place Value",
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
      "accepted_answers": [
          correct_word,
          correct_word.replace("-", " "),
      ],
      "explanation": (
          f"Read the whole number, use 'and' for decimal point, then read the"
          f" fractional part: **{correct_word}**."
      ),
  }


# ==============================================================================
# OTHER CURRICULUM CHAPTER GENERATORS
# ==============================================================================


def gen_multiply_whole():
  n1, n2 = random.randint(120, 350), random.randint(12, 35)
  prod = n1 * n2
  return {
      "template_id": "ch2_multiply_typed",
      "topic": "Chapter 2: Multiply Whole Numbers",
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


def gen_divide_one_digit():
  div, quot, rem = (
      random.randint(4, 9),
      random.randint(35, 95),
      random.randint(1, 3),
  )
  total = (quot * div) + rem
  correct = f"{quot} R{rem}"
  return {
      "template_id": "ch3_divide_typed",
      "topic": "Chapter 3: Divide by a One-Digit Divisor",
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
      "template_id": "ch4_divide_two_digit_typed",
      "topic": "Chapter 4: Divide by a Two-Digit Divisor",
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


def gen_add_sub_decimals():
  d1, d2 = round(random.uniform(14.25, 48.75), 2), round(
      random.uniform(5.15, 18.50), 2
  )
  mode = random.choice(["add", "sub"])
  res = round(d1 + d2, 2) if mode == "add" else round(d1 - d2, 2)
  q_str = f"{d1:.2f} + {d2:.2f}" if mode == "add" else f"{d1:.2f} - {d2:.2f}"
  return {
      "template_id": "ch5_decimals_ops_typed",
      "topic": "Chapter 5: Add and Subtract Decimals",
      "hint": (
          "Line up the decimal points straight down before adding or"
          " subtracting."
      ),
      "input_type": "text",
      "placeholder": "Enter decimal result",
      "scenario": "Align decimal points vertically before adding or subtracting.",
      "question": f"Calculate: **{q_str}**",
      "answer": f"{res:.2f}",
      "accepted_answers": [f"{res:.2f}", str(res)],
      "explanation": f"Sum/Difference = **{res:.2f}**.",
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
      "template_id": "ch6_mult_decimals",
      "topic": "Chapter 6: Multiply and Divide Decimals",
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


def gen_expressions_patterns():
  a, b, c = (
      random.randint(3, 8),
      random.randint(2, 6),
      random.randint(3, 7),
  )
  val = (a + b) * c
  return {
      "template_id": "ch7_pemdas_typed",
      "topic": "Chapter 7: Expressions and Patterns",
      "hint": "Parentheses always come first in Order of Operations!",
      "input_type": "text",
      "placeholder": "Enter evaluated number",
      "scenario": "Order of operations (PEMDAS).",
      "question": f"Evaluate: **({a} + {b}) × {c}**",
      "answer": str(val),
      "accepted_answers": [str(val)],
      "explanation": f"({a} + {b}) = {a+b}. {a+b} × {c} = **{val}**.",
  }


def gen_fractions_decimals():
  pairs = [(1, 2, "0.5"), (1, 4, "0.25"), (3, 4, "0.75"), (1, 5, "0.2"), (2, 5, "0.4"), (3, 5, "0.6"), (4, 5, "0.8")]
  num, den, dec = random.choice(pairs)
  opts = helper_shuffle_options(
      dec, [f"0.{num}{den}", f"0.{num*2}", f"{float(dec)+0.15:.2f}"]
  )
  return {
      "template_id": "ch8_frac_to_dec",
      "topic": "Chapter 8: Fractions and Decimals",
      "hint": "Divide the numerator by the denominator, or think of tenths.",
      "input_type": "radio",
      "diagram": "fraction_bar",
      "diagram_params": {"num": num, "den": den},
      "scenario": "Convert fractions to equivalent decimals.",
      "question": f"What is the decimal equivalent of **{num}/{den}**?",
      "options": opts,
      "answer": dec,
      "explanation": f"{num}/{den} = **{dec}**.",
  }


def gen_add_sub_fractions():
  opts = helper_shuffle_options("3/4", ["2/6", "1/4", "2/4"])
  return {
      "template_id": "ch9_unlike_fractions",
      "topic": "Chapter 9: Add and Subtract Fractions",
      "hint": "Find the least common denominator so the bottoms match.",
      "input_type": "radio",
      "options": opts,
      "scenario": "Find common denominators before adding or subtracting.",
      "question": "What is **1/2 + 1/4** in simplest form?",
      "answer": "3/4",
      "explanation": "2/4 + 1/4 = **3/4**.",
  }


def gen_mult_div_fractions():
  whole, unit_den = random.randint(2, 6), random.choice([3, 4, 5])
  res = whole * unit_den
  return {
      "template_id": "ch10_divide_unit_fractions_typed",
      "topic": "Chapter 10: Multiply and Divide Fractions",
      "hint": (
          f"Dividing by 1/{unit_den} means multiplying the whole number by"
          f" {unit_den}."
      ),
      "input_type": "text",
      "placeholder": "Enter whole number",
      "scenario": (
          f"A carpenter has {whole} feet of wood cut into 1/{unit_den} foot"
          " pieces."
      ),
      "question": f"How many pieces are made? (**{whole} ÷ 1/{unit_den}**)",
      "answer": str(res),
      "accepted_answers": [str(res), f"{res} pieces"],
      "explanation": f"{whole} × {unit_den} = **{res}**.",
  }


def gen_measurement():
  feet = random.randint(3, 9)
  inches = feet * 12
  return {
      "template_id": "ch11_measurement_typed",
      "topic": "Chapter 11: Measurement",
      "hint": "1 foot has 12 inches, so multiply feet by 12.",
      "input_type": "text",
      "placeholder": "Enter number of inches",
      "scenario": "1 foot = 12 inches.",
      "question": f"Convert **{feet} feet** into **inches**:",
      "answer": f"{inches} inches",
      "accepted_answers": [str(inches), f"{inches} in", f"{inches} inches"],
      "explanation": f"{feet} × 12 = **{inches} inches**.",
  }


def gen_geometry_compound_l():
  l1, l2 = random.choice([4, 5, 6]), random.choice([4, 6, 8])
  h1, h2, w = (
      random.choice([10, 12, 14]),
      random.choice([3, 4, 5]),
      random.choice([3, 4, 5]),
  )
  v1, v2 = l1 * w * h1, l2 * w * h2
  total_v = v1 + v2
  return {
      "template_id": "ch12_compound_l_typed",
      "topic": "Chapter 12: Geometry",
      "hint": (
          "Split the shape into Box 1 and Box 2. Find length × width × height"
          " for each, then add them!"
      ),
      "input_type": "text",
      "placeholder": "Enter total cubic volume",
      "scenario": (
          "To find compound volume, split into non-overlapping rectangular"
          " prisms."
      ),
      "diagram": "compound_l_prism",
      "diagram_params": {"l1": l1, "h1": h1, "l2": l2, "h2": h2, "w": w},
      "breakdown_diagram": "compound_l_breakdown",
      "breakdown_details": {
          "v1_calc": f"{l1} × {w} × {h1} = {v1} cu in",
          "v2_calc": f"{l2} × {w} × {h2} = {v2} cu in",
          "tot_calc": f"{v1} + {v2} = {total_v} cu in",
      },
      "question": (
          "What is the total volume of the compound 3D solid shown in the"
          " diagram (in cubic inches)?"
      ),
      "answer": f"{total_v} cu in",
      "accepted_answers": [
          str(total_v),
          f"{total_v} cu in",
          f"{total_v} cubic inches",
      ],
      "explanation": (
          f"Prism 1: {v1} cu in | Prism 2: {v2} cu in | Total = **{total_v} cu"
          " in**."
      ),
  }


def gen_geometry_unit_cubes():
  l1, l2 = random.choice([2, 3]), random.choice([2, 3])
  h1, h2, w = (
      random.choice([3, 4]),
      random.choice([1, 2]),
      random.choice([2, 3]),
  )
  v1, v2 = l1 * h1 * w, l2 * h2 * w
  total_cubes = v1 + v2
  return {
      "template_id": "ch12_unit_cubes_typed",
      "topic": "Chapter 12: Geometry",
      "hint": "Count or calculate the blocks in each section, then add.",
      "input_type": "text",
      "placeholder": "Enter count of unit cubes",
      "scenario": "Each cube represents 1 cubic unit.",
      "diagram": "unit_cubes_compound",
      "diagram_params": {"l1": l1, "h1": h1, "l2": l2, "h2": h2, "w": w},
      "breakdown_diagram": "unit_cubes_breakdown",
      "breakdown_details": {
          "v1_calc": f"{l1} × {h1} × {w} = {v1} cubes",
          "v2_calc": f"{l2} × {h2} × {w} = {v2} cubes",
          "tot_calc": f"{v1} + {v2} = {total_cubes} cubic units",
      },
      "question": (
          "How many 1-unit cubes make up this solid, and what is its total"
          " volume?"
      ),
      "answer": f"{total_cubes} cubic units",
      "accepted_answers": [
          str(total_cubes),
          f"{total_cubes} cubes",
          f"{total_cubes} cubic units",
      ],
      "explanation": (
          f"Left Section = {v1} | Right Section = {v2} | Total = **{total_cubes}"
          " cubic units**."
      ),
  }


# Master Generator Registry
GENERATORS = [
    # Unit 3: Place Value Review Suite
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
    # Additional Chapters
    gen_multiply_whole,
    gen_divide_one_digit,
    gen_divide_two_digit,
    gen_add_sub_decimals,
    gen_mult_div_decimals,
    gen_expressions_patterns,
    gen_fractions_decimals,
    gen_add_sub_fractions,
    gen_mult_div_fractions,
    gen_measurement,
    gen_geometry_compound_l,
    gen_geometry_unit_cubes,
]

TOPIC_TO_GENERATORS = {}
for g in GENERATORS:
  sample = g()
  TOPIC_TO_GENERATORS.setdefault(sample["topic"], []).append(g)

ALL_TOPICS = sorted(list(TOPIC_TO_GENERATORS.keys()))
init_db()

# ==============================================================================
# 5. STREAMLIT APPLICATION UI
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
      "🎯 Focus Chapters:", ALL_TOPICS, default=["Unit 3: Place Value"]
  )

  st.markdown("---")
  if st.session_state.student:
    st.header("📊 Chapter Mastery")
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

  # Adaptive Weighting: If she has lower mastery on a topic, weight that topic higher
  weights = []
  for f in cooling:
    dummy = f()
    score = st.session_state.mastery.get(dummy["topic"], 0.0)
    # Inverse weight: lower mastery score gives higher selection probability
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
  st.warning("👈 Please select at least one chapter.")
  st.stop()

if (
    st.session_state.current_q is None
    or st.session_state.current_q["topic"] not in selected_topics
):
  pick_next_question()

q = st.session_state.current_q
if q is None:
  st.warning("No questions available for the selected chapter.")
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
st.caption(f"Chapter: **{q['topic']}**{lesson_badge}")
st.info(f"**Context / Directions:**\n\n{q['scenario']}")

if "table" in q:
  st.write("**Reference Table:**")
  st.dataframe(pd.DataFrame(q["table"]), hide_index=True)

if "diagram" in q:
  img_buffer = generate_diagram(q["diagram"], q.get("diagram_params", {}))
  st.image(img_buffer, width=540)

# Scaffolding Hint Button (Allows learning before failing)
if "hint" in q and not st.session_state.answered:
  with st.expander("💡 Need a Teacher Hint? Click here before answering!"):
    st.info(q["hint"])

if "breakdown_diagram" in q:
  with st.expander("💡 Click for Visual Breakdown & Strategy"):
    st.markdown(
        "**How to decompose (split) this compound shape into two regular"
        " prisms:**"
    )
    breakdown_buf = generate_diagram(
        q["breakdown_diagram"], q.get("diagram_params", {})
    )
    st.image(breakdown_buf, width=580)
    bd = q.get("breakdown_details", {})
    st.markdown(f"""
        * **Prism 1 (Blue):** Length × Width × Height = `{bd.get('v1_calc', '')}`
        * **Prism 2 (Green):** Length × Width × Height = `{bd.get('v2_calc', '')}`
        * **Total Volume:** Add both volumes together: **`{bd.get('tot_calc', '')}`**
        """)

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

  if "breakdown_diagram" in q:
    st.markdown("### 🧩 Step-by-Step Visual Decomposition:")
    ans_breakdown_buf = generate_diagram(
        q["breakdown_diagram"], q.get("diagram_params", {})
    )
    st.image(ans_breakdown_buf, width=600)

if st.session_state.answered and st.button("Next Question ➡️"):
  pick_next_question()
  st.rerun()
