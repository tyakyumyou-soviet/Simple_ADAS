"""タッチ操作で使う一貫した線画アイコン。文字ラベルと併用する。"""
import math
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap


def _draw_icon(name: str, color: str) -> QPixmap:
    scale = 3
    pixmap = QPixmap(24 * scale, 24 * scale)
    pixmap.setDevicePixelRatio(scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    if name in {"reverse", "front"}:
        font = QFont("Arial")
        font.setPixelSize(22)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(0, 0, 24, 24), int(Qt.AlignmentFlag.AlignCenter), "R" if name == "reverse" else "F")
    elif name == "switch":
        painter.drawLine(QPointF(4, 8), QPointF(19, 8))
        painter.drawLine(QPointF(16, 5), QPointF(19, 8))
        painter.drawLine(QPointF(16, 11), QPointF(19, 8))
        painter.drawLine(QPointF(20, 16), QPointF(5, 16))
        painter.drawLine(QPointF(8, 13), QPointF(5, 16))
        painter.drawLine(QPointF(8, 19), QPointF(5, 16))
    elif name == "back":
        painter.drawLine(QPointF(20, 12), QPointF(5, 12))
        painter.drawLine(QPointF(10, 7), QPointF(5, 12))
        painter.drawLine(QPointF(10, 17), QPointF(5, 12))
    elif name == "event":
        outline = QPainterPath()
        outline.moveTo(3, 8)
        outline.lineTo(7, 8)
        outline.lineTo(8.5, 5.5)
        outline.lineTo(15.5, 5.5)
        outline.lineTo(17, 8)
        outline.lineTo(21, 8)
        outline.lineTo(21, 19)
        outline.lineTo(3, 19)
        outline.closeSubpath()
        painter.drawPath(outline)
        painter.drawEllipse(QRectF(9, 10, 6, 6))
    elif name == "settings":
        painter.drawEllipse(QRectF(6, 6, 12, 12))
        painter.drawEllipse(QRectF(10, 10, 4, 4))
        for i in range(8):
            angle = i * math.pi / 4
            painter.drawLine(QPointF(12 + 6 * math.cos(angle), 12 + 6 * math.sin(angle)),
                             QPointF(12 + 9 * math.cos(angle), 12 + 9 * math.sin(angle)))
    elif name == "home":
        outline = QPainterPath()
        outline.moveTo(3, 11)
        outline.lineTo(12, 4)
        outline.lineTo(21, 11)
        outline.moveTo(6, 10)
        outline.lineTo(6, 20)
        outline.lineTo(18, 20)
        outline.lineTo(18, 10)
        outline.moveTo(10, 20)
        outline.lineTo(10, 14)
        outline.lineTo(14, 14)
        outline.lineTo(14, 20)
        painter.drawPath(outline)
    else:
        painter.end()
        raise ValueError(f"unknown icon: {name}")
    painter.end()
    return pixmap


def button_icon(name: str) -> QIcon:
    icon = QIcon()
    icon.addPixmap(_draw_icon(name, "#edf4f6"), QIcon.Mode.Normal)
    icon.addPixmap(_draw_icon(name, "#a4b3bc"), QIcon.Mode.Disabled)
    return icon
