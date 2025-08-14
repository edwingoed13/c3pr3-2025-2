import React, { useState, useEffect, useCallback } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  ResponsiveContainer,
  LabelList,
} from "recharts";
import {
  Users,
  RefreshCw,
  AlertCircle,
  MapPin,
  Download,
  User,
  Search,
} from "lucide-react";
import "./App.css";

// Componentes reutilizables para la UI
const LoadingSpinner = () => (
  <div className="flex items-center justify-center p-8">
    <RefreshCw className="animate-spin h-8 w-8 text-white" />
    <span className="ml-2 text-lg text-white">Cargando datos...</span>
  </div>
);

const ErrorDisplay = ({ error, onRetry }) => (
  <div className="flex flex-col items-center justify-center p-8 bg-red-800 border border-red-700 rounded-lg text-white">
    <AlertCircle className="h-12 w-12 text-red-400 mb-4" />
    <h3 className="text-lg font-semibold text-white mb-2">
      Error al cargar datos
    </h3>
    <p className="text-red-200 mb-4 text-center">{error}</p>
    <button
      onClick={onRetry}
      className="bg-red-500 hover:bg-red-600 text-white px-4 py-2 rounded-lg flex items-center"
    >
      <RefreshCw className="h-4 w-4 mr-2" />
      Reintentar
    </button>
  </div>
);

// Componente para la sección de descarga de fichas
const FichaDownloadSection = ({
  dni,
  setDni,
  handleDownloadFicha,
  downloadLoading,
  downloadError,
  downloadSuccess,
  setDownloadError,
  setDownloadSuccess,
}) => (
  <div className="card ficha-download-card">
    <div className="ficha-download-content">
      <div className="ficha-download-header">
        <div className="ficha-icon-wrapper">
          <Download className="ficha-icon" />
        </div>
        <div>
          <h3 className="ficha-title">Descargar Ficha de Inscripción</h3>
          <p className="ficha-description">
            Ingrese el DNI del estudiante para generar su ficha
          </p>
        </div>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          handleDownloadFicha();
        }}
        className="ficha-form"
      >
        <div className="dni-input-group">
          <User className="dni-input-icon" />
          <input
            type="text"
            inputMode="numeric"
            pattern="[0-9]*"
            placeholder="Ingrese DNI (8 dígitos)"
            value={dni}
            onChange={(e) => {
              const value = e.target.value.replace(/\D/g, "");
              setDni(value);
              if (downloadError || downloadSuccess) {
                setDownloadError(null);
                setDownloadSuccess(null);
              }
            }}
            className="dni-input"
            maxLength={8}
          />
          <button
            type="submit"
            disabled={downloadLoading || !dni || dni.length !== 8}
            className="btn-download"
          >
            {downloadLoading ? (
              <RefreshCw className="animate-spin h-4 w-4" />
            ) : (
              <Search className="h-4 w-4" />
            )}
            {downloadLoading ? "Buscando..." : "Buscar y Descargar"}
          </button>
        </div>
      </form>

      {downloadError && (
        <div className="download-message error-message">
          <AlertCircle className="h-4 w-4" />
          <span>{downloadError}</span>
        </div>
      )}

      {downloadSuccess && (
        <div className="download-message success-message">
          <Download className="h-4 w-4" />
          <span>{downloadSuccess}</span>
        </div>
      )}
    </div>
  </div>
);

// Componente de tabla para mostrar datos de áreas
const AreaTable = ({ data: tableData, title }) => (
  <>
    <h3 className="chart-title mb-6">{title}</h3>
    <div className="table-container">
      <table className="data-table">
        <thead className="table-header">
          <tr>
            <th>Área</th>
            <th>Total</th>
          </tr>
        </thead>
        <tbody className="table-body">
          {tableData.map((row, index) => (
            <tr key={index}>
              <td className="table-cell-primary">{row.area}</td>
              <td className="table-cell-number">{row.total}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  </>
);

// Componente de tabla para mostrar datos de turnos
const TurnoTable = ({ data: tableData, title }) => (
  <>
    <h3 className="chart-title mb-6">{title}</h3>
    <div className="table-container">
      <table className="data-table">
        <thead className="table-header">
          <tr>
            <th>Área</th>
            <th>Turno</th>
            <th>Total</th>
          </tr>
        </thead>
        <tbody className="table-body">
          {tableData.map((row, index) => (
            <tr key={index}>
              <td className="table-cell-primary">{row.area}</td>
              <td className="table-cell-secondary">{row.turno}</td>
              <td className="table-cell-number">{row.total}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  </>
);

// Nuevo componente de tabla para mostrar totales por sede
const SedeTable = ({ data: tableData, title }) => (
  <>
    <h3 className="chart-title mb-6">{title}</h3>
    <div className="table-container">
      <table className="data-table">
        <thead className="table-header">
          <tr>
            <th>Sede</th>
            <th>Total</th>
          </tr>
        </thead>
        <tbody className="table-body">
          {tableData.map((row, index) => (
            <tr key={index}>
              <td className="table-cell-primary">{row.sede}</td>
              <td className="table-cell-number">{row.total}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  </>
);

// Componente principal
const StudentDashboard = () => {
  const API_BASE_URL =
    process.env.REACT_APP_API_URL ||
    (process.env.NODE_ENV === "production"
      ? "https://cepreuna-backend.onrender.com"
      : "http://localhost:8000");

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [selectedView, setSelectedView] = useState("todos"); // Vista predeterminada: Total por Área
  const [selectedSede, setSelectedSede] = useState("");

  // Estados para la funcionalidad de descarga de fichas
  const [dni, setDni] = useState("");
  const [downloadLoading, setDownloadLoading] = useState(false);
  const [downloadError, setDownloadError] = useState(null);
  const [downloadSuccess, setDownloadSuccess] = useState(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const response = await fetch(
        `${API_BASE_URL}/api/estudiantes/estadisticas`
      );

      if (!response.ok) {
        const errorData = await response
          .json()
          .catch(() => ({ detail: `Error del servidor: ${response.status}` }));
        throw new Error(
          errorData.detail || "Ocurrió un error al cargar los datos."
        );
      }

      const result = await response.json();

      if (!result || typeof result !== "object") {
        throw new Error("Datos inválidos recibidos de la API");
      }

      setData(result);
      setLastUpdate(
        new Date().toLocaleString("es-PE", {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        })
      );
    } catch (err) {
      console.error("Error fetching data:", err);
      setError(err.message || "Error desconocido al obtener los datos.");
    } finally {
      setLoading(false);
    }
  }, [API_BASE_URL]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleDownloadFicha = useCallback(async () => {
    if (!dni || dni.trim().length !== 8) {
      setDownloadError("Por favor ingrese un DNI válido de 8 dígitos");
      return;
    }

    try {
      setDownloadLoading(true);
      setDownloadError(null);
      setDownloadSuccess(null);

      const response = await fetch(`${API_BASE_URL}/api/estudiantes/ficha`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dni: dni.trim() }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(
          errorData.detail || `Error ${response.status}: ${response.statusText}`
        );
      }

      const result = await response.json();

      if (result.download_url) {
        window.open(result.download_url, "_blank");

        const studentData = result.estudiante.estudiante;
        let studentName = "Estudiante encontrado";

        if (studentData && studentData.nombres) {
          const nombres = studentData.nombres || "";
          const apellidos = `${studentData.paterno || ""} ${
            studentData.materno || ""
          }`.trim();
          studentName = `${nombres} ${apellidos}`.trim();
        }

        setDownloadSuccess(`Ficha generada para: ${studentName}`);
        setDni("");
      } else {
        throw new Error("No se recibió URL de descarga válida");
      }
    } catch (err) {
      console.error("Error downloading ficha:", err);
      setDownloadError(
        err.message || "Error al generar la ficha de inscripción"
      );
    } finally {
      setDownloadLoading(false);
    }
  }, [dni, setDownloadError, setDownloadSuccess, API_BASE_URL]); // Dependencias del useCallback

  useEffect(() => {
    if (downloadSuccess || downloadError) {
      const timer = setTimeout(() => {
        setDownloadSuccess(null);
        setDownloadError(null);
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [downloadSuccess, downloadError]);

  // Funciones para preparar los datos para la visualización
  const getAvailableSedes = () => {
    if (!data || !data.por_sede) return [];
    return Object.keys(data.por_sede);
  };

  const prepareAreaChartData = () => {
    if (!data || !data.por_area) return [];
    return Object.entries(data.por_area).map(([area, total], index) => ({
      area,
      total,
      fill: institutionalColors[index % institutionalColors.length],
    }));
  };

  const prepareSedeTotalsData = () => {
    if (!data || !data.por_sede) return [];
    return Object.entries(data.por_sede).map(([sede, total]) => ({
      sede,
      total,
    }));
  };

  const prepareSedeAreaData = (sede) => {
    if (!data || !data.detalle_completo) return [];
    const result = [];
    Object.entries(data.detalle_completo).forEach(([area, sedes]) => {
      if (sedes[sede]) {
        const total = Object.values(sedes[sede]).reduce(
          (sum, count) => sum + count,
          0
        );
        if (total > 0) result.push({ area, total });
      }
    });
    return result.sort((a, b) => b.total - a.total);
  };

  const prepareTurnoData = (sede) => {
    if (!data || !data.detalle_completo) return [];
    const result = [];
    Object.entries(data.detalle_completo).forEach(([area, sedes]) => {
      if (sedes[sede]) {
        Object.entries(sedes[sede]).forEach(([turno, total]) => {
          if (total > 0) result.push({ area, turno, total });
        });
      }
    });
    return result.sort(
      (a, b) => a.area.localeCompare(b.area) || a.turno.localeCompare(b.turno)
    );
  };

  // Paleta de colores para el gráfico de barras
  const institutionalColors = [
    "#16285c",
    "#df5e1e",
    "#5fa65a",
    "#293d7c",
    "#c3521b",
    "#4a884a",
    "#85325c",
    "#007bff",
  ];

  // Componente de etiqueta personalizada para mostrar el valor en el centro de la barra
  const renderCustomizedLabel = (props) => {
    const { x, y, width, height, value } = props;

    return (
      <g>
        {/* Fondo con brillo para el número */}
        <rect
          x={x + width / 2 - 25}
          y={y + height / 2 - 12}
          width={50}
          height={24}
          fill="rgba(255,255,255,0.2)"
          rx={12}
          style={{ filter: "drop-shadow(0 0 5px rgba(255,255,255,0.3))" }}
        />
        <text
          x={x + width / 2}
          y={y + height / 2 + 5}
          fill="#ffffff"
          textAnchor="middle"
          dominantBaseline="middle"
          fontSize={14}
          fontWeight="bold"
          style={{ filter: "drop-shadow(0 0 3px rgba(0,0,0,0.8))" }}
        >
          {value}
        </text>
      </g>
    );
  };

  if (loading) {
    return (
      <div className="dashboard-container">
        <div className="dashboard-content">
          <h1 className="dashboard-title">CEPREUNA - Ciclo 2025-II</h1>
          <LoadingSpinner />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="dashboard-container">
        <div className="dashboard-content">
          <h1 className="dashboard-title">CEPREUNA - Ciclo 2025-II</h1>
          <ErrorDisplay error={error} onRetry={fetchData} />
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="dashboard-container">
        <div className="dashboard-content">
          <h1 className="dashboard-title">CEPREUNA - Ciclo 2025-II</h1>
          <div className="empty-state">
            <p className="empty-state-text">No hay datos disponibles</p>
            <button onClick={fetchData} className="btn-update mt-4">
              Recargar
            </button>
          </div>
        </div>
      </div>
    );
  }

  const availableSedes = getAvailableSedes();

  return (
    <div className="dashboard-container">
      <div className="dashboard-content">
        <div className="dashboard-header animate-fade-in-up">
          <div className="title-container">
            <h1 className="dashboard-title">
              <span className="title-accent">CEPREUNA</span>
              <span className="title-cycle">Ciclo 2025-II</span>
            </h1>
            <div className="title-underline"></div>
          </div>
          <div className="header-actions">
            {lastUpdate && (
              <span className="last-update pulse-glow">
                Última actualización: {lastUpdate}
              </span>
            )}
            <button
              onClick={() => fetchData()}
              disabled={loading}
              className="btn-update modern-btn"
            >
              <RefreshCw
                className={`${loading ? "loading-spinner" : ""}`}
                size={16}
              />
              Actualizar
            </button>
          </div>
        </div>

        {/* Nuevo contenedor para las dos tarjetas de resumen */}
        <div className="dashboard-summary">
          <div className="card total-students-card animate-slide-in-right">
            <div className="total-students-content">
              <Users className="total-students-icon" />
              <div>
                <p className="total-students-label">Total de Estudiantes</p>
                <p className="total-students-number">{data.total || 0}</p>
              </div>
            </div>
          </div>

          <FichaDownloadSection
            dni={dni}
            setDni={setDni}
            handleDownloadFicha={handleDownloadFicha}
            downloadLoading={downloadLoading}
            downloadError={downloadError}
            setDownloadError={setDownloadError}
            downloadSuccess={downloadSuccess}
            setDownloadSuccess={setDownloadSuccess}
          />
        </div>

        {/* Selector de vista actualizado */}
        <div className="card selector-card styled-selector-card">
          <div className="selector-content">
            <div className="selector-row">
              <div className="selector-group">
                <label className="selector-label">Vista:</label>
                <select
                  value={selectedView}
                  onChange={(e) => {
                    setSelectedView(e.target.value);
                    setSelectedSede("");
                  }}
                  className="selector-dropdown"
                >
                  <option value="todos">Total por Área</option>
                  <option value="por_sede_resumen">Total por Sede</option>
                  <option value="por_sede_detalle">Detalle por Sede</option>
                </select>
              </div>

              {selectedView === "por_sede_detalle" && (
                <div className="selector-group">
                  <label className="selector-label">Sede:</label>
                  <select
                    value={selectedSede}
                    onChange={(e) => setSelectedSede(e.target.value)}
                    className="selector-dropdown"
                  >
                    <option value="">Seleccionar sede...</option>
                    {availableSedes.map((sede) => (
                      <option key={sede} value={sede}>
                        {sede}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Contenido condicional para cada vista */}
        {selectedView === "todos" && (
          <div className="card gradient-card">
            <h3 className="chart-title mb-6">Estudiantes por Área</h3>
            <div className="chart-container">
              <ResponsiveContainer width="100%" height={400}>
                <BarChart
                  data={prepareAreaChartData()}
                  margin={{ top: 20, right: 30, left: 20, bottom: 80 }} // Aumenta bottom margin
                  barCategoryGap="20%" // Controla el espacio entre grupos de barras
                  barGap={10} // Espacio entre barras individuales
                >
                  <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.5} />
                  <XAxis
                    dataKey="area"
                    textAnchor="middle"
                    fontSize={11} // Reduce un poco el tamaño
                    interval={0}
                    stroke="white"
                    tick={{ fill: "white" }}
                    height={60} // Fija una altura para el eje X
                    angle={0} // Asegura texto horizontal
                  />
                  <YAxis stroke="white" tick={{ fill: "white" }} />
                  <Bar
                    dataKey="total"
                    // Elimina barSize completamente para que se ajuste automáticamente
                  >
                    <LabelList
                      dataKey="total"
                      content={renderCustomizedLabel}
                      position="center"
                    />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}

        {selectedView === "por_sede_resumen" && (
          <div className="card gradient-card">
            <SedeTable
              data={prepareSedeTotalsData()}
              title="Total de Estudiantes por Sede"
            />
          </div>
        )}

        {selectedView === "por_sede_detalle" && selectedSede && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="card gradient-card">
              <AreaTable
                data={prepareSedeAreaData(selectedSede)}
                title={`Estudiantes por Área - ${selectedSede}`}
              />
            </div>
            <div className="card gradient-card">
              <TurnoTable
                data={prepareTurnoData(selectedSede)}
                title={`Estudiantes por Área y Turno - ${selectedSede}`}
              />
            </div>
          </div>
        )}

        {selectedView === "por_sede_detalle" && !selectedSede && (
          <div className="card empty-state gradient-card">
            <MapPin className="h-12 w-12 text-gray-200 mx-auto mb-4" />
            <p className="empty-state-text text-white">
              Selecciona una sede para ver los datos detallados
            </p>
          </div>
        )}

        {data.ultimo_update && (
          <div className="mt-8 bg-white p-4 rounded-lg shadow-lg">
            <p className="text-sm text-gray-600">
              Datos actualizados desde el servidor:{" "}
              {new Date(data.ultimo_update).toLocaleString()}
            </p>
          </div>
        )}
      </div>
    </div>
  );
};

export default StudentDashboard;
