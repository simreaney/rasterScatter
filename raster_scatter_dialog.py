import math

import numpy as np

from qgis.PyQt.QtCore import Qt, QPointF, QRectF, QTimer
from qgis.PyQt.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QWidget,
    QSpinBox,
    QVBoxLayout,
)
from qgis.core import (
    Qgis,
    QgsCoordinateTransform,
    QgsMessageLog,
    QgsPointXY,
    QgsProject,
    QgsRasterLayer,
)


class ScatterPlotWidget(QWidget):
    _COLOR_RAMPS = {
        "Viridis": [
            (0.0, (68, 1, 84)),
            (0.25, (59, 82, 139)),
            (0.5, (33, 145, 140)),
            (0.75, (94, 201, 98)),
            (1.0, (253, 231, 37)),
        ],
        "Inferno": [
            (0.0, (0, 0, 4)),
            (0.25, (87, 15, 109)),
            (0.5, (187, 55, 84)),
            (0.75, (249, 142, 8)),
            (1.0, (252, 255, 164)),
        ],
        "Plasma": [
            (0.0, (13, 8, 135)),
            (0.25, (126, 3, 167)),
            (0.5, (203, 71, 119)),
            (0.75, (248, 149, 64)),
            (1.0, (240, 249, 33)),
        ],
        "Turbo": [
            (0.0, (48, 18, 59)),
            (0.25, (42, 136, 241)),
            (0.5, (41, 202, 118)),
            (0.75, (245, 197, 37)),
            (1.0, (180, 4, 38)),
        ],
        "Greys": [
            (0.0, (245, 245, 245)),
            (0.5, (150, 150, 150)),
            (1.0, (35, 35, 35)),
        ],
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._x_values = np.asarray([], dtype=float)
        self._y_values = np.asarray([], dtype=float)
        self._slope = None
        self._intercept = None
        self._x_label = ""
        self._y_label = ""
        self._title = "Raster Scatter Plot"
        self._plot_type = 0  # 0=scatter, 1=hist2d square, 2=hist2d hex
        self._hist_bins = 50
        self._color_ramp = "Viridis"
        self._view_mode = 0  # 0=2D, 1=3D
        self._plot_3d_type = 0  # 0=histogram, 1=scatter
        self._legend_enabled = True
        self._plot_rect = QRectF()
        self._x_min = 0.0
        self._x_max = 1.0
        self._y_min = 0.0
        self._y_max = 1.0
        self._hover_text = ""
        self._mouse_pos = None
        self._is_dragging = False
        self._last_drag_pos = None
        self._yaw_deg = -35.0
        self._pitch_deg = 45.0
        self._z_scale = 0.95
        self.setMouseTracking(True)

    def set_plot_data(
        self,
        x_values,
        y_values,
        slope,
        intercept,
        x_label,
        y_label,
        title,
        plot_type=0,
        hist_bins=50,
        color_ramp="Viridis",
        view_mode=0,
        plot_3d_type=0,
        legend_enabled=True,
    ):
        self._x_values = np.asarray(x_values, dtype=float)
        self._y_values = np.asarray(y_values, dtype=float)
        self._slope = float(slope)
        self._intercept = float(intercept)
        self._x_label = x_label
        self._y_label = y_label
        self._title = title
        self._plot_type = plot_type
        self._hist_bins = max(5, int(hist_bins))
        self._color_ramp = color_ramp if color_ramp in self._COLOR_RAMPS else "Viridis"
        self._view_mode = int(view_mode)
        self._plot_3d_type = int(plot_3d_type)
        self._legend_enabled = bool(legend_enabled)
        self.update()

    def _event_pos(self, event):
        if hasattr(event, "position"):
            return event.position()
        return QPointF(event.pos())

    def mousePressEvent(self, event):
        if self._view_mode == 1 and event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = True
            self._last_drag_pos = self._event_pos(event)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        current_pos = self._event_pos(event)
        self._mouse_pos = current_pos

        if self._view_mode == 1 and self._is_dragging and self._last_drag_pos is not None:
            delta = current_pos - self._last_drag_pos
            self._yaw_deg -= float(delta.x()) * 0.35
            self._pitch_deg = max(15.0, min(80.0, self._pitch_deg - float(delta.y()) * 0.25))
            self._last_drag_pos = current_pos
        else:
            self._update_hover_info()

        self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = False
            self._last_drag_pos = None
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if self._view_mode == 1:
            delta = event.angleDelta().y()
            factor = 1.08 if delta > 0 else 1.0 / 1.08
            self._z_scale = max(0.35, min(2.2, self._z_scale * factor))
            self.update()
            event.accept()
            return
        super().wheelEvent(event)

    def leaveEvent(self, event):
        self._mouse_pos = None
        self._hover_text = ""
        self.update()
        super().leaveEvent(event)

    def _contains_mouse_in_plot(self):
        if self._mouse_pos is None:
            return False
        return self._plot_rect.contains(self._mouse_pos)

    def _update_hover_info(self):
        self._hover_text = ""
        if self._view_mode != 0 or not self._contains_mouse_in_plot():
            return

        x_span = self._x_max - self._x_min
        y_span = self._y_max - self._y_min
        if x_span == 0 or y_span == 0:
            return

        u = (self._mouse_pos.x() - self._plot_rect.left()) / self._plot_rect.width()
        v = (self._plot_rect.bottom() - self._mouse_pos.y()) / self._plot_rect.height()
        u = max(0.0, min(1.0, float(u)))
        v = max(0.0, min(1.0, float(v)))

        x_value = self._x_min + u * x_span
        y_value = self._y_min + v * y_span
        hover_parts = [f"x={x_value:.6g}", f"y={y_value:.6g}"]

        if self._plot_type == 1:
            n_bins = self._hist_bins
            counts, x_edges, y_edges = np.histogram2d(
                self._x_values,
                self._y_values,
                bins=n_bins,
                range=[[self._x_min, self._x_max], [self._y_min, self._y_max]],
            )
            i = int(np.searchsorted(x_edges, x_value, side="right") - 1)
            j = int(np.searchsorted(y_edges, y_value, side="right") - 1)
            if 0 <= i < n_bins and 0 <= j < n_bins:
                hover_parts.append(f"count={int(counts[i, j])}")
        elif self._plot_type == 2:
            n_cols = max(6, self._hist_bins // 2)
            sqrt3 = math.sqrt(3)
            r_pix = self._plot_rect.width() / (n_cols * sqrt3)

            def pix_to_axial(px, py):
                q = (sqrt3 / 3 * px - py / 3) / r_pix
                r = (2 / 3 * py) / r_pix
                return q, r

            def round_axial(q, r):
                s = -q - r
                rq, rr, rs = round(q), round(r), round(s)
                if abs(rq - q) > abs(rr - r) and abs(rq - q) > abs(rs - s):
                    rq = -rr - rs
                elif abs(rr - r) > abs(rs - s):
                    rr = -rq - rs
                return rq, rr

            hex_counts = {}
            for xv, yv in zip(self._x_values, self._y_values):
                px = ((float(xv) - self._x_min) / x_span) * self._plot_rect.width()
                py = ((self._y_max - float(yv)) / y_span) * self._plot_rect.height()
                key = round_axial(*pix_to_axial(px, py))
                hex_counts[key] = hex_counts.get(key, 0) + 1

            mouse_px = self._mouse_pos.x() - self._plot_rect.left()
            mouse_py = self._mouse_pos.y() - self._plot_rect.top()
            key = round_axial(*pix_to_axial(mouse_px, mouse_py))
            hover_parts.append(f"count={hex_counts.get(key, 0)}")

        self._hover_text = "   ".join(hover_parts)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("white"))

        if self._x_values.size == 0 or self._y_values.size == 0:
            painter.setPen(QColor("#555555"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No data to plot")
            return

        left_margin = 75
        right_margin = 20
        top_margin = 50
        bottom_margin = 70
        plot_rect = self.rect().adjusted(left_margin, top_margin, -right_margin, -bottom_margin)

        x_min = float(np.min(self._x_values))
        x_max = float(np.max(self._x_values))
        y_min = float(np.min(self._y_values))
        y_max = float(np.max(self._y_values))

        x_padding = (x_max - x_min) * 0.05 or 1.0
        y_padding = (y_max - y_min) * 0.05 or 1.0
        x_min -= x_padding
        x_max += x_padding
        y_min -= y_padding
        y_max += y_padding

        self._plot_rect = QRectF(plot_rect)
        self._x_min = x_min
        self._x_max = x_max
        self._y_min = y_min
        self._y_max = y_max
        self._update_hover_info()

        painter.setPen(QPen(QColor("#666666"), 1))
        painter.drawRect(plot_rect)

        def map_x(value):
            return plot_rect.left() + ((value - x_min) / (x_max - x_min)) * plot_rect.width()

        def map_y(value):
            return plot_rect.bottom() - ((value - y_min) / (y_max - y_min)) * plot_rect.height()

        painter.setPen(QPen(QColor("#d0d0d0"), 1))
        for fraction in np.linspace(0.0, 1.0, 6):
            x = plot_rect.left() + fraction * plot_rect.width()
            y = plot_rect.top() + fraction * plot_rect.height()
            painter.drawLine(int(x), plot_rect.top(), int(x), plot_rect.bottom())
            painter.drawLine(plot_rect.left(), int(y), plot_rect.right(), int(y))

        painter.setClipRect(plot_rect)
        if self._view_mode == 1:
            if self._plot_3d_type == 1:
                self._draw_scatter3d(painter, plot_rect, x_min, x_max, y_min, y_max)
            else:
                self._draw_hist3d(painter, plot_rect, x_min, x_max, y_min, y_max)
        else:
            if self._plot_type == 1:
                self._draw_hist2d_square(painter, plot_rect, x_min, x_max, y_min, y_max, map_x, map_y)
            elif self._plot_type == 2:
                self._draw_hist2d_hex(painter, plot_rect, map_x, map_y)
            else:
                self._draw_scatter(painter, map_x, map_y)
                if self._slope is not None and self._intercept is not None:
                    x_line = np.array([x_min, x_max], dtype=float)
                    y_line = self._slope * x_line + self._intercept
                    painter.setPen(QPen(QColor("crimson"), 2))
                    painter.drawLine(int(map_x(float(x_line[0]))), int(map_y(float(y_line[0]))), int(map_x(float(x_line[1]))), int(map_y(float(y_line[1]))))
        painter.setClipping(False)

        # Redraw border on top of clipped data
        painter.setPen(QPen(QColor("#666666"), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(plot_rect)

        if self._legend_enabled and self._should_show_color_legend():
            self._draw_color_legend(painter, plot_rect)

        painter.setPen(QColor("#222222"))
        painter.setFont(QFont(painter.font().family(), 11, QFont.Weight.Bold))
        painter.drawText(self.rect().adjusted(10, 8, -10, -10), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter, self._title)

        painter.setFont(QFont(painter.font().family(), 11))
        painter.drawText(plot_rect.adjusted(0, 8, 0, 0), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft, f"{x_min:.3g}")
        painter.drawText(plot_rect.adjusted(0, 8, 0, 0), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight, f"{x_max:.3g}")
        painter.drawText(plot_rect.adjusted(-55, -6, -6, 0), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, f"{y_max:.3g}")
        painter.drawText(plot_rect.adjusted(-55, 0, -6, 6), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft, f"{y_min:.3g}")

        painter.drawText(plot_rect.adjusted(-50, -25, 0, 40), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter, self._x_label)

        if self._hover_text and self._contains_mouse_in_plot():
            painter.setPen(QPen(QColor("#9a9a9a"), 1, Qt.PenStyle.DashLine))
            painter.drawLine(int(self._mouse_pos.x()), plot_rect.top(), int(self._mouse_pos.x()), plot_rect.bottom())
            painter.drawLine(plot_rect.left(), int(self._mouse_pos.y()), plot_rect.right(), int(self._mouse_pos.y()))

            info_rect = QRectF(plot_rect.left() + 10, plot_rect.top() + 10, min(320, plot_rect.width() - 20), 26)
            painter.setPen(QPen(QColor("#bbbbbb"), 1))
            painter.setBrush(QColor(255, 255, 255, 228))
            painter.drawRoundedRect(info_rect, 4, 4)
            painter.setPen(QColor("#222222"))
            painter.setFont(QFont(painter.font().family(), 9))
            painter.drawText(info_rect.adjusted(8, 2, -6, -2), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._hover_text)

        painter.save()
        painter.translate(20, plot_rect.center().y() + 60)
        painter.rotate(-90)
        painter.drawText(QRectF(0, 0, plot_rect.height(), 28), Qt.AlignmentFlag.AlignCenter, self._y_label)
        painter.restore()

    def _draw_scatter(self, painter, map_x, map_y):
        color = QColor("#2a9d8f")
        color.setAlpha(178)  # alpha 0.7
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        point_radius = 3
        for x_value, y_value in zip(self._x_values, self._y_values):
            painter.drawEllipse(
                int(map_x(float(x_value))) - point_radius,
                int(map_y(float(y_value))) - point_radius,
                point_radius * 2,
                point_radius * 2,
            )

    def _draw_hist2d_square(self, painter, plot_rect, x_min, x_max, y_min, y_max, map_x, map_y):
        n_bins = self._hist_bins
        counts, x_edges, y_edges = np.histogram2d(
            self._x_values, self._y_values, bins=n_bins,
            range=[[x_min, x_max], [y_min, y_max]],
        )
        max_count = counts.max()
        if max_count == 0:
            return
        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(n_bins):
            for j in range(n_bins):
                c = counts[i, j]
                if c == 0:
                    continue
                px0 = int(map_x(x_edges[i]))
                px1 = int(map_x(x_edges[i + 1]))
                py0 = int(map_y(y_edges[j + 1]))
                py1 = int(map_y(y_edges[j]))
                painter.fillRect(px0, py0, max(1, px1 - px0), max(1, py1 - py0),
                                 self._density_color(c / max_count))

    def _draw_hist2d_hex(self, painter, plot_rect, map_x, map_y):
        n_cols = max(6, self._hist_bins // 2)
        sqrt3 = math.sqrt(3)
        r_pix = plot_rect.width() / (n_cols * sqrt3)

        def pix_to_axial(px, py):
            q = (sqrt3 / 3 * px - py / 3) / r_pix
            r = (2 / 3 * py) / r_pix
            return q, r

        def round_axial(q, r):
            s = -q - r
            rq, rr, rs = round(q), round(r), round(s)
            if abs(rq - q) > abs(rr - r) and abs(rq - q) > abs(rs - s):
                rq = -rr - rs
            elif abs(rr - r) > abs(rs - s):
                rr = -rq - rs
            return rq, rr

        hex_counts = {}
        for xv, yv in zip(self._x_values, self._y_values):
            px = map_x(float(xv)) - plot_rect.left()
            py = map_y(float(yv)) - plot_rect.top()
            key = round_axial(*pix_to_axial(px, py))
            hex_counts[key] = hex_counts.get(key, 0) + 1

        max_count = max(hex_counts.values()) if hex_counts else 1
        painter.setPen(Qt.PenStyle.NoPen)
        for (q, r), count in hex_counts.items():
            cx = plot_rect.left() + r_pix * (sqrt3 * q + sqrt3 / 2 * r)
            cy = plot_rect.top() + r_pix * (3 / 2 * r)
            painter.setBrush(self._density_color(count / max_count))
            hex_pts = QPolygonF([
                QPointF(
                    cx + r_pix * math.cos(math.pi / 6 + i * math.pi / 3),
                    cy + r_pix * math.sin(math.pi / 6 + i * math.pi / 3),
                )
                for i in range(6)
            ])
            painter.drawPolygon(hex_pts)

    def _draw_hist3d(self, painter, plot_rect, x_min, x_max, y_min, y_max):
        n_bins = self._hist_bins
        counts, x_edges, y_edges = np.histogram2d(
            self._x_values,
            self._y_values,
            bins=n_bins,
            range=[[x_min, x_max], [y_min, y_max]],
        )
        max_count = counts.max()
        if max_count == 0:
            return

        x_span = (x_max - x_min) or 1.0
        y_span = (y_max - y_min) or 1.0

        def to_unit(value, low, span):
            return (value - low) / span

        bars = []
        for i in range(n_bins):
            for j in range(n_bins):
                count = counts[i, j]
                if count <= 0:
                    continue
                u0 = to_unit(x_edges[i], x_min, x_span)
                u1 = to_unit(x_edges[i + 1], x_min, x_span)
                v0 = to_unit(y_edges[j], y_min, y_span)
                v1 = to_unit(y_edges[j + 1], y_min, y_span)
                h = float(count / max_count)
                _, depth = self._project_3d((u0 + u1) * 0.5, (v0 + v1) * 0.5, h * 0.5, plot_rect)
                bars.append((depth, u0, u1, v0, v1, h, count))

        bars.sort(key=lambda item: item[0])
        painter.setPen(QPen(QColor("#202020"), 1))
        show_x_positive = math.cos(math.radians(self._yaw_deg)) >= 0.0
        show_y_positive = math.sin(math.radians(self._yaw_deg)) >= 0.0

        for _, u0, u1, v0, v1, h, count in bars:
            bottom_a, _ = self._project_3d(u0, v0, 0.0, plot_rect)
            bottom_b, _ = self._project_3d(u1, v0, 0.0, plot_rect)
            bottom_c, _ = self._project_3d(u1, v1, 0.0, plot_rect)
            bottom_d, _ = self._project_3d(u0, v1, 0.0, plot_rect)

            top_a, _ = self._project_3d(u0, v0, h, plot_rect)
            top_b, _ = self._project_3d(u1, v0, h, plot_rect)
            top_c, _ = self._project_3d(u1, v1, h, plot_rect)
            top_d, _ = self._project_3d(u0, v1, h, plot_rect)

            density = float(count / max_count)

            top_face = QPolygonF([top_a, top_b, top_c, top_d])
            side_x = (
                QPolygonF([bottom_b, bottom_c, top_c, top_b])
                if show_x_positive
                else QPolygonF([bottom_a, bottom_d, top_d, top_a])
            )
            side_y = (
                QPolygonF([bottom_c, bottom_d, top_d, top_c])
                if show_y_positive
                else QPolygonF([bottom_a, bottom_b, top_b, top_a])
            )

            painter.setBrush(self._density_color(density, brightness=0.62))
            painter.drawPolygon(side_x)

            painter.setBrush(self._density_color(density, brightness=0.78))
            painter.drawPolygon(side_y)

            painter.setBrush(self._density_color(density, brightness=1.0))
            painter.drawPolygon(top_face)

    def _draw_scatter3d(self, painter, plot_rect, x_min, x_max, y_min, y_max):
        n_bins = self._hist_bins
        counts, x_edges, y_edges = np.histogram2d(
            self._x_values,
            self._y_values,
            bins=n_bins,
            range=[[x_min, x_max], [y_min, y_max]],
        )
        max_count = counts.max()
        if max_count == 0:
            return

        x_span = (x_max - x_min) or 1.0
        y_span = (y_max - y_min) or 1.0

        x_idx = np.searchsorted(x_edges, self._x_values, side="right") - 1
        y_idx = np.searchsorted(y_edges, self._y_values, side="right") - 1
        x_idx = np.clip(x_idx, 0, n_bins - 1)
        y_idx = np.clip(y_idx, 0, n_bins - 1)

        points = []
        for xv, yv, i, j in zip(self._x_values, self._y_values, x_idx, y_idx):
            density = counts[i, j]
            if density <= 0:
                continue
            u = (float(xv) - x_min) / x_span
            v = (float(yv) - y_min) / y_span
            z = float(density / max_count)
            pt, depth = self._project_3d(u, v, z, plot_rect)
            points.append((depth, density / max_count, pt))

        points.sort(key=lambda item: item[0])

        painter.setPen(Qt.PenStyle.NoPen)
        for _, density_norm, point in points:
            painter.setBrush(self._density_color(density_norm, brightness=1.0))
            radius = 2.0 + 2.4 * float(density_norm)
            painter.drawEllipse(point, radius, radius)

    def _project_3d(self, u, v, z, plot_rect):
        x = float(u) - 0.5
        y = float(v) - 0.5
        z = float(z) * self._z_scale

        yaw = math.radians(self._yaw_deg)
        pitch = math.radians(self._pitch_deg)

        x1 = x * math.cos(yaw) - y * math.sin(yaw)
        y1 = x * math.sin(yaw) + y * math.cos(yaw)

        y2 = y1 * math.cos(pitch) - z * math.sin(pitch)
        z2 = y1 * math.sin(pitch) + z * math.cos(pitch)

        scale = min(plot_rect.width(), plot_rect.height()) * 0.9
        center_x = plot_rect.center().x()
        center_y = plot_rect.center().y() + 30.0

        screen_x = center_x + x1 * scale
        screen_y = center_y + y2 * scale
        return QPointF(screen_x, screen_y), z2

    def set_legend_enabled(self, enabled):
        self._legend_enabled = bool(enabled)
        self.update()

    def has_plot_data(self):
        return self._x_values.size > 0 and self._y_values.size > 0

    def _should_show_color_legend(self):
        if self._view_mode == 1:
            return True
        return self._plot_type in (1, 2)

    def _draw_color_legend(self, painter, plot_rect):
        legend_width = 16
        legend_height = min(180, max(110, plot_rect.height() // 3))
        legend_x = plot_rect.right() - legend_width - 10
        legend_y = plot_rect.top() + 16
        legend_rect = QRectF(float(legend_x), float(legend_y), float(legend_width), float(legend_height))

        for index in range(int(legend_height)):
            t = 1.0 - (index / max(1, legend_height - 1))
            painter.setPen(self._density_color(t))
            y = legend_y + index
            painter.drawLine(legend_x, y, legend_x + legend_width, y)

        painter.setPen(QPen(QColor("#555555"), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(legend_rect)

        painter.setPen(QColor("#222222"))
        painter.setFont(QFont(painter.font().family(), 9))
        painter.drawText(
            QRectF(legend_rect.left() - 28, legend_rect.top() - 16, legend_rect.width() + 56, 14),
            Qt.AlignmentFlag.AlignCenter,
            "Density",
        )
        painter.drawText(
            QRectF(legend_rect.right() + 6, legend_rect.top() - 7, 36, 14),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "High",
        )
        painter.drawText(
            QRectF(legend_rect.right() + 6, legend_rect.bottom() - 7, 36, 14),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "Low",
        )

    def _density_color(self, t, brightness=1.0):
        t = max(0.0, min(1.0, float(t)))
        stops = self._COLOR_RAMPS.get(self._color_ramp, self._COLOR_RAMPS["Viridis"])
        for index in range(len(stops) - 1):
            left_stop, left_color = stops[index]
            right_stop, right_color = stops[index + 1]
            if t <= right_stop:
                segment = 0.0 if right_stop == left_stop else (t - left_stop) / (right_stop - left_stop)
                r = int(left_color[0] + segment * (right_color[0] - left_color[0]))
                g = int(left_color[1] + segment * (right_color[1] - left_color[1]))
                b = int(left_color[2] + segment * (right_color[2] - left_color[2]))
                break
        else:
            r, g, b = stops[-1][1]

        brightness = max(0.2, min(1.2, float(brightness)))
        r = int(max(0, min(255, r * brightness)))
        g = int(max(0, min(255, g * brightness)))
        b = int(max(0, min(255, b * brightness)))
        return QColor(r, g, b)


class RasterScatterDialog(QDialog):
    def __init__(self, iface):
        super().__init__(iface.mainWindow())
        self.iface = iface
        self.setWindowTitle("Raster Scatter Plot")
        self.resize(1100, 780)

        self.x_combo = QComboBox()
        self.y_combo = QComboBox()
        self.max_samples_spin = QSpinBox()
        self.max_samples_spin.setRange(100, 1000000)
        self.max_samples_spin.setSingleStep(1000)
        self.max_samples_spin.setValue(50000)

        self.plot_type_combo = QComboBox()
        self.plot_type_combo.addItem("Scatter", 0)
        self.plot_type_combo.addItem("2D Histogram (Square bins)", 1)
        self.plot_type_combo.addItem("2D Histogram (Hex bins)", 2)

        self.bins_spin = QSpinBox()
        self.bins_spin.setRange(5, 250)
        self.bins_spin.setSingleStep(5)
        self.bins_spin.setValue(50)

        self.color_ramp_combo = QComboBox()
        for ramp_name in ScatterPlotWidget._COLOR_RAMPS:
            self.color_ramp_combo.addItem(ramp_name, ramp_name)

        self.view_mode_combo = QComboBox()
        self.view_mode_combo.addItem("2D", 0)
        self.view_mode_combo.addItem("3D", 1)

        self.plot_3d_type_combo = QComboBox()
        self.plot_3d_type_combo.addItem("3D Histogram", 0)
        self.plot_3d_type_combo.addItem("3D Scatter", 1)

        self.legend_checkbox = QCheckBox("Show legend")
        self.legend_checkbox.setChecked(True)

        self.auto_refresh_checkbox = QCheckBox("Auto refresh on option change")
        self.auto_refresh_checkbox.setChecked(True)
        self.auto_refresh_checkbox.setToolTip(
            "When enabled, the plot updates automatically whenever an option changes.\n"
            "When disabled, use \"Resample now\" to update the plot manually."
        )

        self.plot_button = QPushButton("Resample now")
        self.plot_button.setToolTip(
            "When auto refresh is enabled, the plot updates automatically when options change.\n"
            "Use this to force an immediate re-sample of the rasters, or to apply\n"
            "pending option changes while auto refresh is disabled."
        )
        self.save_button = QPushButton("Save PNG")
        self.close_button = QPushButton("Close")
        self.result_label = QLabel("Choose two raster layers to plot.")
        self.result_label.setWordWrap(True)

        self.plot_widget = ScatterPlotWidget()

        # Cached sample data so rendering-only options (bins, colour ramp,
        # view mode, etc.) can redraw instantly without re-sampling rasters.
        self._cached_x_values = None
        self._cached_y_values = None
        self._cached_slope = None
        self._cached_intercept = None
        self._cached_r_squared = None
        self._cached_x_label = ""
        self._cached_y_label = ""

        self._needs_resample = False
        self._pending_render = False
        self._auto_update_timer = QTimer(self)
        self._auto_update_timer.setSingleShot(True)
        self._auto_update_timer.setInterval(250)
        self._auto_update_timer.timeout.connect(self._run_auto_update)

        self._build_ui()
        self.refresh_layers()

        self.plot_button.clicked.connect(self.plot_scatter)
        self.save_button.clicked.connect(self.save_plot_png)
        self.close_button.clicked.connect(self.close)
        self.legend_checkbox.toggled.connect(self._on_legend_toggled)
        self.auto_refresh_checkbox.toggled.connect(self._on_auto_refresh_toggled)
        self.view_mode_combo.currentIndexChanged.connect(self._on_view_mode_changed)
        self._on_view_mode_changed()

        # Options that change which raster pixels are sampled require a
        # full re-sample; the rest only affect how the cached data is drawn.
        self.x_combo.currentIndexChanged.connect(self._schedule_full_replot)
        self.y_combo.currentIndexChanged.connect(self._schedule_full_replot)
        self.max_samples_spin.valueChanged.connect(self._schedule_full_replot)

        self.plot_type_combo.currentIndexChanged.connect(self._schedule_render_replot)
        self.bins_spin.valueChanged.connect(self._schedule_render_replot)
        self.color_ramp_combo.currentIndexChanged.connect(self._schedule_render_replot)
        self.view_mode_combo.currentIndexChanged.connect(self._schedule_render_replot)
        self.plot_3d_type_combo.currentIndexChanged.connect(self._schedule_render_replot)
        self.legend_checkbox.toggled.connect(self._schedule_render_replot)

    def _build_ui(self):
        form = QFormLayout()
        form.addRow("X raster", self.x_combo)
        form.addRow("Y raster", self.y_combo)
        form.addRow("Max samples", self.max_samples_spin)
        form.addRow("Plot type", self.plot_type_combo)
        form.addRow("Histogram bins", self.bins_spin)
        form.addRow("Colour ramp", self.color_ramp_combo)
        form.addRow("View", self.view_mode_combo)
        form.addRow("3D plot", self.plot_3d_type_combo)
        form.addRow("Legend", self.legend_checkbox)
        form.addRow("", self.auto_refresh_checkbox)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self.plot_button)
        button_row.addWidget(self.save_button)
        button_row.addWidget(self.close_button)

        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addWidget(self.plot_widget, stretch=1)
        root.addWidget(self.result_label)
        root.addLayout(button_row)

    def refresh_layers(self):
        current_x = self.x_combo.currentData()
        current_y = self.y_combo.currentData()

        raster_layers = [
            layer
            for layer in QgsProject.instance().mapLayers().values()
            if isinstance(layer, QgsRasterLayer) and layer.isValid()
        ]

        self.x_combo.blockSignals(True)
        self.y_combo.blockSignals(True)
        self.x_combo.clear()
        self.y_combo.clear()

        for layer in raster_layers:
            label = layer.name()
            self.x_combo.addItem(label, layer.id())
            self.y_combo.addItem(label, layer.id())

        if current_x is not None:
            self._restore_selection(self.x_combo, current_x)
        if current_y is not None:
            self._restore_selection(self.y_combo, current_y)

        self.x_combo.blockSignals(False)
        self.y_combo.blockSignals(False)

        if self.x_combo.count() == 0 or self.y_combo.count() == 0:
            self.result_label.setText("Add at least two raster layers to the project.")

    def _restore_selection(self, combo, layer_id):
        index = combo.findData(layer_id)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _selected_layer(self, combo):
        layer_id = combo.currentData()
        if not layer_id:
            return None
        return QgsProject.instance().mapLayer(layer_id)

    def _on_view_mode_changed(self, *_args):
        is_three_d = self.view_mode_combo.currentData() == 1
        self.plot_type_combo.setEnabled(not is_three_d)
        self.plot_3d_type_combo.setEnabled(is_three_d)
        if is_three_d:
            self.plot_type_combo.setToolTip("2D plot type is only used in 2D view.")
        else:
            self.plot_type_combo.setToolTip("")

    def _on_legend_toggled(self, checked):
        self.plot_widget.set_legend_enabled(checked)

    def _on_auto_refresh_toggled(self, checked):
        if checked and (self._needs_resample or self._pending_render):
            self._pending_render = False
            self._auto_update_timer.start()

    def _schedule_full_replot(self, *_args):
        self._needs_resample = True
        if self.auto_refresh_checkbox.isChecked():
            self._auto_update_timer.start()

    def _schedule_render_replot(self, *_args):
        if self._cached_x_values is None:
            return
        if not self.auto_refresh_checkbox.isChecked():
            self._pending_render = True
            return
        self._auto_update_timer.start()

    def _run_auto_update(self):
        if self._needs_resample:
            self._needs_resample = False
            self.plot_scatter()
        else:
            self._pending_render = False
            self._render_from_cache()

    def _render_from_cache(self):
        if self._cached_x_values is None or self._cached_y_values is None:
            return

        self.plot_widget.set_plot_data(
            self._cached_x_values,
            self._cached_y_values,
            self._cached_slope,
            self._cached_intercept,
            self._cached_x_label,
            self._cached_y_label,
            "Raster Scatter Plot",
            plot_type=self.plot_type_combo.currentData(),
            hist_bins=self.bins_spin.value(),
            color_ramp=self.color_ramp_combo.currentData(),
            view_mode=self.view_mode_combo.currentData(),
            plot_3d_type=self.plot_3d_type_combo.currentData(),
            legend_enabled=self.legend_checkbox.isChecked(),
        )
        self._update_summary_label(self._cached_x_values.size)

    def save_plot_png(self):
        if not self.plot_widget.has_plot_data():
            QMessageBox.warning(self, "Raster Scatter Plot", "Create a plot before saving to PNG.")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Plot as PNG",
            "raster_scatter_plot.png",
            "PNG Images (*.png)",
        )
        if not file_path:
            return

        if not file_path.lower().endswith(".png"):
            file_path = f"{file_path}.png"

        if not self.plot_widget.grab().save(file_path, "PNG"):
            QMessageBox.warning(self, "Raster Scatter Plot", "Failed to save PNG file.")
            return

        self.result_label.setText(f"Saved plot to: {file_path}")

    def _provider_sample(self, provider, point, band):
        value = provider.sample(point, band)
        if isinstance(value, tuple):
            sampled_value = value[0]
            ok = bool(value[1]) if len(value) > 1 else True
        else:
            sampled_value = value
            ok = True

        if sampled_value is None:
            return math.nan, False

        try:
            sampled_value = float(sampled_value)
        except (TypeError, ValueError):
            return math.nan, False

        return sampled_value, ok and math.isfinite(sampled_value)

    def _transform_point(self, transform, point):
        try:
            return transform.transform(point), True
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"Skipping sample point that failed to reproject: {exc}",
                "Raster Scatter Plot",
                level=Qgis.Warning,
            )
            return point, False

    def _sample_rasters(self, x_layer, y_layer, max_samples):
        x_provider = x_layer.dataProvider()
        y_provider = y_layer.dataProvider()

        x_extent = x_provider.extent()
        width = max(1, x_layer.width())
        height = max(1, x_layer.height())

        total_pixels = width * height
        step = max(1, int(math.sqrt(total_pixels / max_samples)))

        transform = None
        if x_layer.crs().isValid() and y_layer.crs().isValid() and x_layer.crs() != y_layer.crs():
            transform = QgsCoordinateTransform(x_layer.crs(), y_layer.crs(), QgsProject.instance())

        pixel_width = x_extent.width() / width
        pixel_height = x_extent.height() / height

        x_values = []
        y_values = []

        for row in range(0, height, step):
            y_coord = x_extent.yMaximum() - ((row + 0.5) * pixel_height)
            for col in range(0, width, step):
                x_coord = x_extent.xMinimum() + ((col + 0.5) * pixel_width)
                point = QgsPointXY(x_coord, y_coord)

                x_value, x_ok = self._provider_sample(x_provider, point, 1)
                if not x_ok:
                    continue

                sample_point = point
                if transform is not None:
                    sample_point, transformed_ok = self._transform_point(transform, point)
                    if not transformed_ok:
                        continue

                y_value, y_ok = self._provider_sample(y_provider, sample_point, 1)
                if not y_ok:
                    continue

                x_values.append(x_value)
                y_values.append(y_value)

        return np.asarray(x_values, dtype=float), np.asarray(y_values, dtype=float)

    def plot_scatter(self):
        self._auto_update_timer.stop()
        self._needs_resample = False
        self._pending_render = False

        x_layer = self._selected_layer(self.x_combo)
        y_layer = self._selected_layer(self.y_combo)

        if x_layer is None or y_layer is None:
            QMessageBox.warning(self, "Raster Scatter Plot", "Select two valid raster layers.")
            return

        try:
            x_values, y_values = self._sample_rasters(x_layer, y_layer, self.max_samples_spin.value())
        except Exception as exc:
            QMessageBox.critical(self, "Raster Scatter Plot", f"Failed to sample rasters: {exc}")
            return

        if x_values.size < 2 or y_values.size < 2:
            QMessageBox.warning(self, "Raster Scatter Plot", "Not enough overlapping valid samples were found.")
            return

        slope, intercept = np.polyfit(x_values, y_values, 1)
        predicted = slope * x_values + intercept
        residual_sum = np.sum((y_values - predicted) ** 2)
        total_sum = np.sum((y_values - np.mean(y_values)) ** 2)
        r_squared = 1.0 if total_sum == 0 else 1.0 - (residual_sum / total_sum)

        self._cached_x_values = x_values
        self._cached_y_values = y_values
        self._cached_slope = float(slope)
        self._cached_intercept = float(intercept)
        self._cached_r_squared = r_squared
        self._cached_x_label = x_layer.name()
        self._cached_y_label = y_layer.name()

        self._render_from_cache()

    def _update_summary_label(self, sample_count):
        equation = f"y = {self._cached_slope:.6g}x + {self._cached_intercept:.6g}"
        summary = (
            f"{equation}\n"
            f"R2 = {self._cached_r_squared:.6g}\n"
            f"Samples = {sample_count}\n"
            f"Bins = {self.bins_spin.value()}\n"
            f"Ramp = {self.color_ramp_combo.currentData()}\n"
            f"View = {self.view_mode_combo.currentText()}\n"
            f"3D plot = {self.plot_3d_type_combo.currentText()}\n"
            f"Legend = {'On' if self.legend_checkbox.isChecked() else 'Off'}"
        )
        self.result_label.setText(summary.replace("\n", "   "))
