$(document).ready(function(){
	$("form.editor").submit(function () {
		$.ajax({
			url: $(this).attr("action"),
			data: $(this).serialize(),
			dataType: "json",
			type: "POST",
			success: function (data) {
				if (data.status == "error")
					alert(data.error);
				else if (data.status == "redirect")
					window.location.href = data.url;
			},
			error: function (data) {
				alert("Could not save the page for some reason.");
			}
		});
		return false;
	});
});
