def test_network_namespace_service_instantiation():
    """NetworkNamespaceService should be instantiable on non-WLANPi systems.

    Fails before the fix because __init__ unconditionally calls pid_dir.mkdir()
    on /home/wlanpi/..., which requires elevated permissions on non-WLANPi systems.
    """
    from wlanpi_core.services.network_namespace_service import NetworkNamespaceService

    service = NetworkNamespaceService()
    assert service is not None
