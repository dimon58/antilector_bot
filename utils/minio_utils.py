import logging

from libcloud.storage.base import Container, StorageDriver
from libcloud.storage.types import ContainerDoesNotExistError

logger = logging.getLogger(__name__)


def get_container_safe(driver: StorageDriver, container_name: str) -> Container:
    try:
        return driver.get_container(container_name)
    except ContainerDoesNotExistError:
        logger.info("Creating container %s", container_name)
        return driver.create_container(container_name)
