#!/bin/sh

ARGS="$@"
THISDIR="$(cd $(dirname "$0") && pwd)"
SERVICE_NAME="dbus-p1"

# Check for a previous install with the same name
SERVICE_PATH="/service/${SERVICE_NAME}"
if [ -e "${SERVICE_PATH}" ]; then
    >&2 echo "Service path ${SERVICE_PATH} already exists. Remove it to continue."
    exit 1
fi
SERVICE_DIR="${THISDIR}/service"
if [ -d "${SERVICE_DIR}" ]; then
    >&2 echo "Service output dir '$(dirname $0)/service' already exists. Remove it to continue."
    exit 2
fi

# Build the service dir in this dir
echo "Creating service dir '${SERVICE_DIR}'"
mkdir -p "${SERVICE_DIR}"
echo "#!/bin/sh" > "${SERVICE_DIR}/run"
echo "exec ${THISDIR}/run.sh ${ARGS} 2>&1" >> "${SERVICE_DIR}/run"
chmod +x "${SERVICE_DIR}/run"

RC_LOCAL=/data/rc.local
# Check if rc.local exists
if [ ! -x "${RC_LOCAL}" ]; then
    echo "Creating executable file '${RC_LOCAL}'"
    echo "#!/bin/sh\n" > "${RC_LOCAL}"
    chmod +x "${RC_LOCAL}"
fi

# Add a line to rc.local to (auto)start the serivce at boot
grep -q "${SERVICE_PATH}" "${RC_LOCAL}"
if [ $? != 0 ]; then
    # No entry for a service with this name in the rc.local, lets add it
    echo "Adding line to '${RC_LOCAL}' to autostart this service at boot"
    echo "ln -s ${SERVICE_DIR} ${SERVICE_PATH}" >> "${RC_LOCAL}"
fi

echo "Starting the new service right away"
ln -sf "${SERVICE_DIR}" "${SERVICE_PATH}"

echo "Service is now installed and started in the background"
