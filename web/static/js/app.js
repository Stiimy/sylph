/* Sylph Dashboard - Global JavaScript */

// Mise a jour du statut de l'agent dans la sidebar
function updateAgentStatus() {
    fetch('/agent/api/status')
        .then(r => r.json())
        .then(data => {
            const indicator = document.getElementById('agent-status-indicator');
            const text = document.getElementById('agent-status-text');
            if (!indicator || !text) return;
            
            const status = data.service_status;
            if (status === 'running') {
                indicator.querySelector('i').className = 'bi bi-circle-fill text-success';
                text.textContent = 'En cours';
            } else if (status === 'stopped' || status === 'inactive') {
                indicator.querySelector('i').className = 'bi bi-circle-fill text-secondary';
                text.textContent = 'Arrete';
            } else if (status === 'failed') {
                indicator.querySelector('i').className = 'bi bi-circle-fill text-danger';
                text.textContent = 'Echoue';
            } else {
                indicator.querySelector('i').className = 'bi bi-circle-fill text-warning';
                text.textContent = status;
            }
        })
        .catch(() => {
            const text = document.getElementById('agent-status-text');
            if (text) text.textContent = 'Erreur';
        });
}

// Mettre a jour toutes les 30 secondes
updateAgentStatus();
setInterval(updateAgentStatus, 30000);
