from PyQt5.QtCore import QAbstractTableModel, QModelIndex, Qt


class CaseTableModel(QAbstractTableModel):
    def __init__(self, rows=None):
        super().__init__()
        self._rows = rows or []

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return 0

    def data(self, index, role=Qt.DisplayRole):
        return None
